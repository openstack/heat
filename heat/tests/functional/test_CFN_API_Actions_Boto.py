# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#

import os
import util
import verify
import re
import nose
from nose.plugins.attrib import attr
import unittest
import json
import datetime


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'api', 'cfn', 'boto'])
class CfnApiBotoFunctionalTest(unittest.TestCase):
    '''
    This test launches a wordpress stack then attempts to verify
    correct operation of all actions supported by the heat CFN API

    Note we use class-level fixtures to avoid setting up a new stack
    for every test method, we set up the stack once then do all the
    tests, this means all tests methods are performed on one class
    instance, instead of creating a new class for every method, which
    is the normal nose unittest.TestCase behavior.

    The nose docs are a bit vague on how to do this, but it seems that
    (setup|teardown)All works and they have to be classmethods.

    Contrary to the nose docs, the class can be a unittest.TestCase subclass

    This version of the test uses the boto client library, hence uses AWS auth
    and checks the boto-parsed results rather than parsing the XML directly
    '''
    @classmethod
    def setupAll(cls):
        print "SETUPALL"
        template = 'WordPress_Single_Instance.template'

        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
                         'DBUsername=dbuser',
                         'DBPassword=' + os.environ['OS_PASSWORD']])

        cls.logical_resource_name = 'WikiDatabase'
        cls.logical_resource_type = 'AWS::EC2::Instance'

        # Just to get the assert*() methods
        class CfnApiFunctions(unittest.TestCase):
            @unittest.skip('Not a real test case')
            def runTest(self):
                pass

        inst = CfnApiFunctions()
        cls.stack = util.StackBoto(inst, template, 'F17', 'x86_64', 'cfntools',
                                   stack_paramstr)
        cls.WikiDatabase = util.Instance(inst, cls.logical_resource_name)

        try:
            cls.stack.create()
            cls.WikiDatabase.wait_for_boot()
            cls.WikiDatabase.check_cfntools()
            cls.WikiDatabase.wait_for_provisioning()

            cls.logical_resource_status = "CREATE_COMPLETE"

            # Save some compiled regexes and strings for response validation
            cls.time_re = re.compile(
                "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
            cls.description_re = re.compile(
                "^AWS CloudFormation Sample Template")
            cls.stack_status = "CREATE_COMPLETE"
            cls.stack_status_reason = "Stack successfully created"
            cls.stack_timeout = 60
            cls.stack_disable_rollback = True

            # Match the expected format for an instance's physical resource ID
            cls.phys_res_id_re = re.compile(
                "^[0-9a-z]*-[0-9a-z]*-[0-9a-z]*-[0-9a-z]*-[0-9a-z]*$")
        finally:
            cls.stack.cleanup()

    @classmethod
    def teardownAll(cls):
        print "TEARDOWNALL"
        cls.stack.cleanup()

    def test_instance(self):
        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        # This is the same as the standard wordress template test
        # but we still do it to prove the stack is OK
        self.assertTrue(self.WikiDatabase.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected"

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.stack.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))

    def testListStacks(self):
        response = self.stack.heatclient.list_stacks()
        prefix = '/ListStacksResponse/ListStacksResult/StackSummaries/member'

        # Extract the StackSummary for this stack
        summary = [s for s in response
                   if s.stack_name == self.stack.stackname]
        self.assertEqual(len(summary), 1)

        # Note the boto StackSummary object does not contain every item
        # output by our API (ie defined in the AWS docs), we can only
        # test what boto encapsulates in the StackSummary class
        self.stack.check_stackid(summary[0].stack_id)

        self.assertEqual(type(summary[0].creation_time), datetime.datetime)

        self.assertTrue(self.description_re.match(
            summary[0].template_description) is not None)

        self.assertEqual(summary[0].stack_name, self.stack.stackname)

        self.assertEqual(summary[0].stack_status, self.stack_status)

        print "ListStacks : OK"

    def testDescribeStacks(self):
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = self.stack.heatclient.describe_stacks(**parameters)

        # Extract the Stack object for this stack
        stacks = [s for s in response
                  if s.stack_name == self.stack.stackname]
        self.assertEqual(len(stacks), 1)

        self.assertEqual(type(stacks[0].creation_time), datetime.datetime)

        self.stack.check_stackid(stacks[0].stack_id)

        self.assertTrue(self.description_re.match(stacks[0].description)
                        is not None)

        self.assertEqual(stacks[0].stack_status_reason,
                         self.stack_status_reason)

        self.assertEqual(stacks[0].stack_name, self.stack.stackname)

        self.assertEqual(stacks[0].stack_status, self.stack_status)

        self.assertEqual(stacks[0].timeout_in_minutes, self.stack_timeout)

        self.assertEqual(stacks[0].disable_rollback,
                         self.stack_disable_rollback)

        # Create a dict to lookup the expected template parameters
        template_parameters = {'DBUsername': 'dbuser',
                               'LinuxDistribution': 'F17',
                               'InstanceType': 'm1.xlarge',
                               'DBRootPassword': 'admin',
                               'KeyName': self.stack.keyname,
                               'DBPassword':
                               os.environ['OS_PASSWORD'],
                               'DBName': 'wordpress'}

        for key, value in template_parameters.iteritems():
            # The parameters returned via the API include a couple
            # of fields which we don't care about (region/stackname)
            # and may possibly end up getting removed, so we just
            # look for the list of expected parameters above
            plist = [p for p in s.parameters if p.key == key]
            self.assertEqual(len(plist), 1)
            self.assertEqual(key, plist[0].key)
            self.assertEqual(value, plist[0].value)

        # Then to a similar lookup to verify the Outputs section
        expected_url = "http://" + self.WikiDatabase.ip + "/wordpress"
        self.assertEqual(len(s.outputs), 1)
        self.assertEqual(s.outputs[0].key, 'WebsiteURL')
        self.assertEqual(s.outputs[0].value, expected_url)

        print "DescribeStacks : OK"

    def testDescribeStackEvents(self):
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = self.stack.heatclient.list_stack_events(**parameters)
        events = [e for e in response
                  if e.logical_resource_id == self.logical_resource_name
                  and e.resource_status == self.logical_resource_status]

        self.assertEqual(len(events), 1)

        self.stack.check_stackid(events[0].stack_id)

        self.assertTrue(re.match("[0-9]*$", events[0].event_id) is not None)

        self.assertEqual(events[0].resource_status,
                         self.logical_resource_status)

        self.assertEqual(events[0].resource_type, self.logical_resource_type)

        self.assertEqual(type(events[0].timestamp), datetime.datetime)

        self.assertEqual(events[0].resource_status_reason, "state changed")

        self.assertEqual(events[0].stack_name, self.stack.stackname)

        self.assertEqual(events[0].logical_resource_id,
                         self.logical_resource_name)

        self.assertTrue(self.phys_res_id_re.match(
                        events[0].physical_resource_id) is not None)

        # Check ResourceProperties, skip pending resolution of #245
        properties = json.loads(events[0].resource_properties)
        self.assertEqual(properties["InstanceType"], "m1.xlarge")

        print "DescribeStackEvents : OK"

    def testGetTemplate(self):
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = self.stack.heatclient.get_template(**parameters)
        self.assertTrue(response is not None)

        result = response['GetTemplateResponse']['GetTemplateResult']
        self.assertTrue(result is not None)
        template = result['TemplateBody']
        self.assertTrue(template is not None)

        # Then sanity check content - I guess we could diff
        # with the template file but for now just check the
        # description looks sane..
        description = template['Description']
        self.assertTrue(self.description_re.match(description) is not None)

        print "GetTemplate : OK"

    def testDescribeStackResource(self):
        parameters = {'StackName': self.stack.stackname,
                      'LogicalResourceId': self.logical_resource_name}
        response = self.stack.heatclient.describe_stack_resource(**parameters)

        # Note boto_client response for this is a dict, if upstream
        # pull request ever gets merged, this will change, see note/
        # link in boto_client.py
        desc_resp = response['DescribeStackResourceResponse']
        self.assertTrue(desc_resp is not None)
        desc_result = desc_resp['DescribeStackResourceResult']
        self.assertTrue(desc_result is not None)
        res = desc_result['StackResourceDetail']
        self.assertTrue(res is not None)

        self.stack.check_stackid(res['StackId'])

        self.assertEqual(res['ResourceStatus'], self.logical_resource_status)

        self.assertEqual(res['ResourceType'], self.logical_resource_type)

        # Note due to issue mentioned above timestamp is a string in this case
        # not a datetime.datetime object
        self.assertTrue(self.time_re.match(res['LastUpdatedTimestamp'])
                        is not None)

        self.assertEqual(res['ResourceStatusReason'], 'state changed')

        self.assertEqual(res['StackName'], self.stack.stackname)

        self.assertEqual(res['LogicalResourceId'], self.logical_resource_name)

        self.assertTrue(self.phys_res_id_re.match(res['PhysicalResourceId'])
                        is not None)

        self.assertTrue("AWS::CloudFormation::Init" in res['Metadata'])

        print "DescribeStackResource : OK"

    def testDescribeStackResources(self):
        parameters = {'NameOrPid': self.stack.stackname,
                      'LogicalResourceId': self.logical_resource_name}
        response = self.stack.heatclient.describe_stack_resources(**parameters)
        self.assertEqual(len(response), 1)

        res = response[0]
        self.assertTrue(res is not None)

        self.stack.check_stackid(res.stack_id)

        self.assertEqual(res.resource_status, self.logical_resource_status)

        self.assertEqual(res.resource_type, self.logical_resource_type)

        self.assertEqual(type(res.timestamp), datetime.datetime)

        self.assertEqual(res.resource_status_reason, 'state changed')

        self.assertEqual(res.stack_name, self.stack.stackname)

        self.assertEqual(res.logical_resource_id, self.logical_resource_name)

        self.assertTrue(self.phys_res_id_re.match(res.physical_resource_id)
                        is not None)

        print "DescribeStackResources : OK"

    def testListStackResources(self):
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = self.stack.heatclient.list_stack_resources(**parameters)
        self.assertEqual(len(response), 1)

        res = response[0]
        self.assertTrue(res is not None)

        self.assertEqual(res.resource_status, self.logical_resource_status)

        self.assertEqual(res.resource_status_reason, 'state changed')

        self.assertEqual(type(res.last_updated_timestamp), datetime.datetime)

        self.assertEqual(res.resource_type, self.logical_resource_type)

        self.assertEqual(res.logical_resource_id, self.logical_resource_name)

        self.assertTrue(self.phys_res_id_re.match(res.physical_resource_id)
                        is not None)

        print "ListStackResources : OK"

    def testValidateTemplate(self):
        # Use stack.format_parameters to get the TemplateBody
        params = self.stack.format_parameters()
        val_params = {'TemplateBody': params['TemplateBody']}
        response = self.stack.heatclient.validate_template(**val_params)
        # Check the response contains all the expected paramter keys
        templ_params = ['DBUsername', 'LinuxDistribution', 'InstanceType',
                        'DBRootPassword', 'KeyName', 'DBPassword', 'DBName']

        resp_params = [p.parameter_key for p in response.template_parameters]
        for param in templ_params:
            self.assertTrue(param in resp_params)
        print "ValidateTemplate : OK"
