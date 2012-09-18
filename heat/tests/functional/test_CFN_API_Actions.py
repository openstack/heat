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


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'api', 'cfn', 'F17'])
class CfnApiFunctionalTest(unittest.TestCase):
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
    '''
    @classmethod
    def setupAll(self):
        print "SETUPALL"
        template = 'WordPress_Single_Instance.template'

        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
                         'DBUsername=dbuser',
                         'DBPassword=' + os.environ['OS_PASSWORD']])

        self.logical_resource_name = 'WikiDatabase'
        self.logical_resource_type = 'AWS::EC2::Instance'
        self.stack = util.Stack(template, 'F17', 'x86_64', 'cfntools',
            stack_paramstr)
        self.WikiDatabase = util.Instance(self.logical_resource_name)
        self.stack.create()
        self.WikiDatabase.wait_for_boot()
        self.WikiDatabase.check_cfntools()
        self.WikiDatabase.wait_for_provisioning()

        self.logical_resource_status = "CREATE_COMPLETE"

        # Save some compiled regexes and strings for response validation
        self.stack_id_re = re.compile("^arn:openstack:heat::admin:stacks/"
                                      + self.stack.stackname)
        self.time_re = re.compile(
            "[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
        self.description_re = re.compile("^AWS CloudFormation Sample Template")
        self.stack_status = "CREATE_COMPLETE"
        self.stack_status_reason = "Stack successfully created"
        self.stack_timeout = str(60)
        self.stack_disable_rollback = "True"

        # Match the expected format for physical resource ID for an instance
        self.phys_res_id_re = re.compile(
            "^[0-9a-z]*-[0-9a-z]*-[0-9a-z]*-[0-9a-z]*-[0-9a-z]*$")

    @classmethod
    def teardownAll(self):
        print "TEARDOWNALL"
        self.stack.cleanup()

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
        client = self.stack.get_heat_client()
        response = client.list_stacks()
        prefix = '/ListStacksResponse/ListStacksResult/StackSummaries/member'

        stack_id = self.stack.response_xml_item(response, prefix, "StackId")
        self.assertTrue(self.stack_id_re.match(stack_id) != None)

        update_time = self.stack.response_xml_item(response, prefix,
                                                   "LastUpdatedTime")
        self.assertTrue(self.time_re.match(update_time) != None)

        create_time = self.stack.response_xml_item(response, prefix,
                                                   "CreationTime")
        self.assertTrue(self.time_re.match(create_time) != None)

        description = self.stack.response_xml_item(response, prefix,
                                                   "TemplateDescription")
        self.assertTrue(self.description_re.match(description) != None)

        status_reason = self.stack.response_xml_item(response, prefix,
                                                     "StackStatusReason")
        self.assertEqual(status_reason, self.stack_status_reason)

        stack_name = self.stack.response_xml_item(response, prefix,
                                                  "StackName")
        self.assertEqual(stack_name, self.stack.stackname)

        stack_status = self.stack.response_xml_item(response, prefix,
                                                    "StackStatus")
        self.assertEqual(stack_status, self.stack_status)

        print "ListStacks : OK"

    def testDescribeStacks(self):
        client = self.stack.get_heat_client()
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = client.describe_stacks(**parameters)
        prefix = '/DescribeStacksResponse/DescribeStacksResult/Stacks/member'

        stack_id = self.stack.response_xml_item(response, prefix, "StackId")
        self.assertTrue(self.stack_id_re.match(stack_id) != None)

        update_time = self.stack.response_xml_item(response, prefix,
                                                   "LastUpdatedTime")
        self.assertTrue(self.time_re.match(update_time) != None)

        create_time = self.stack.response_xml_item(response, prefix,
                                                   "CreationTime")
        self.assertTrue(self.time_re.match(create_time) != None)

        description = self.stack.response_xml_item(response, prefix,
                                                   "Description")
        self.assertTrue(self.description_re.match(description) != None)

        status_reason = self.stack.response_xml_item(response, prefix,
                                                     "StackStatusReason")
        self.assertEqual(status_reason, self.stack_status_reason)

        stack_name = self.stack.response_xml_item(response, prefix,
                                                  "StackName")
        self.assertEqual(stack_name, self.stack.stackname)

        stack_status = self.stack.response_xml_item(response, prefix,
                                                    "StackStatus")
        self.assertEqual(stack_status, self.stack_status)

        stack_timeout = self.stack.response_xml_item(response, prefix,
                                                     "TimeoutInMinutes")
        self.assertEqual(stack_timeout, self.stack_timeout)

        disable_rollback = self.stack.response_xml_item(response, prefix,
                                                     "DisableRollback")
        self.assertEqual(disable_rollback, self.stack_disable_rollback)

        # Create a dict to lookup the expected template parameters
        template_parameters = {'DBUsername': 'dbuser',
                                    'LinuxDistribution': 'F17',
                                    'InstanceType': 'm1.xlarge',
                                    'DBRootPassword': 'admin',
                                    'KeyName': self.stack.keyname,
                                    'DBPassword':
                                        os.environ['OS_PASSWORD'],
                                    'DBName': 'wordpress'}

        # We do a fully qualified xpath lookup to extract the paramter
        # value for each key, then check the extracted value
        param_prefix = prefix + "/Parameters/member"
        for key, value in template_parameters.iteritems():
            lookup = '[ParameterKey="' + key + '" and ParameterValue="' +\
                     value + '"]'
            lookup_value = self.stack.response_xml_item(response,
                                                   param_prefix + lookup,
                                                   "ParameterValue")
            self.assertEqual(lookup_value, value)

        # Then to a similar lookup to verify the Outputs section
        expected_url = "http://" + self.WikiDatabase.ip + "/wordpress"

        outputs_prefix = prefix + "/Outputs/member"
        lookup = '[OutputKey="WebsiteURL" and OutputValue="' + expected_url +\
                 '" and Description="URL for Wordpress wiki"]'
        lookup_value = self.stack.response_xml_item(response,
                                                   outputs_prefix + lookup,
                                                   "OutputValue")
        self.assertEqual(lookup_value, expected_url)

        print "DescribeStacks : OK"

    def testDescribeStackEvents(self):
        client = self.stack.get_heat_client()
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = client.list_stack_events(**parameters)
        prefix = '/DescribeStackEventsResponse/DescribeStackEventsResult/' +\
               'StackEvents/member[LogicalResourceId="' +\
                self.logical_resource_name + '" and ResourceStatus="' +\
                self.logical_resource_status + '"]'

        stack_id = self.stack.response_xml_item(response, prefix, "StackId")
        self.assertTrue(self.stack_id_re.match(stack_id) != None)

        event_id = self.stack.response_xml_item(response, prefix, "EventId")
        self.assertTrue(re.match("[0-9]*$", event_id) != None)

        resource_status = self.stack.response_xml_item(response, prefix,
                                                        "ResourceStatus")
        self.assertEqual(resource_status, self.logical_resource_status)

        resource_type = self.stack.response_xml_item(response, prefix,
                                                        "ResourceType")
        self.assertEqual(resource_type, self.logical_resource_type)

        update_time = self.stack.response_xml_item(response, prefix,
                                                   "Timestamp")
        self.assertTrue(self.time_re.match(update_time) != None)

        status_data = self.stack.response_xml_item(response, prefix,
                                                      "ResourceStatusData")
        self.assertEqual(status_data, "state changed")

        stack_name = self.stack.response_xml_item(response, prefix,
                                                  "StackName")
        self.assertEqual(stack_name, self.stack.stackname)

        log_res_id = self.stack.response_xml_item(response, prefix,
                                                  "LogicalResourceId")
        self.assertEqual(log_res_id, self.logical_resource_name)

        phys_res_id = self.stack.response_xml_item(response, prefix,
                                                  "PhysicalResourceId")
        self.assertTrue(self.phys_res_id_re.match(phys_res_id) != None)

        # Check ResourceProperties, the format of this is not defined
        # by the AWS API spec, so we just check one expected key is there
        rp_prefix = prefix + '/ResourceProperties'
        prop_type = self.stack.response_xml_item(response, rp_prefix,
                                                  "InstanceType")
        self.assertEqual(prop_type, "m1.xlarge")

        print "DescribeStackEvents : OK"

    def testGetTemplate(self):
        client = self.stack.get_heat_client()
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = client.get_template(**parameters)
        prefix = '/GetTemplateResponse/GetTemplateResult'

        # Extract the JSON TemplateBody and prove it parses
        template = self.stack.response_xml_item(response, prefix,
                                                "TemplateBody")
        json_load = json.loads(template)
        self.assertTrue(json_load != None)

        # Then sanity check content - I guess we could diff
        # with the template file but for now just check the
        # description looks sane..
        description = json_load['Description']
        self.assertTrue(self.description_re.match(description) != None)

        print "GetTemplate : OK"

    def testDescribeStackResource(self):
        client = self.stack.get_heat_client()
        parameters = {'StackName': self.stack.stackname,
            'LogicalResourceId': self.logical_resource_name}
        response = client.describe_stack_resource(**parameters)
        prefix = '/DescribeStackResourceResponse/DescribeStackResourceResult'\
               + '/StackResourceDetail'

        stack_id = self.stack.response_xml_item(response, prefix, "StackId")
        self.assertTrue(self.stack_id_re.match(stack_id) != None)

        resource_status = self.stack.response_xml_item(response, prefix,
                                                        "ResourceStatus")
        self.assertEqual(resource_status, self.logical_resource_status)

        resource_type = self.stack.response_xml_item(response, prefix,
                                                        "ResourceType")
        self.assertEqual(resource_type, self.logical_resource_type)

        update_time = self.stack.response_xml_item(response, prefix,
                                                   "LastUpdatedTimestamp")
        self.assertTrue(self.time_re.match(update_time) != None)

        status_reason = self.stack.response_xml_item(response, prefix,
                                                      "ResourceStatusReason")
        self.assertEqual(status_reason, "None")

        stack_name = self.stack.response_xml_item(response, prefix,
                                                  "StackName")
        self.assertEqual(stack_name, self.stack.stackname)

        log_res_id = self.stack.response_xml_item(response, prefix,
                                                  "LogicalResourceId")
        self.assertEqual(log_res_id, self.logical_resource_name)

        phys_res_id = self.stack.response_xml_item(response, prefix,
                                                  "PhysicalResourceId")
        self.assertTrue(self.phys_res_id_re.match(phys_res_id) != None)

        metadata = self.stack.response_xml_item(response, prefix, "Metadata")
        json_load = json.loads(metadata)
        self.assertTrue(json_load != None)
        self.assertTrue("AWS::CloudFormation::Init" in json_load)

        print "DescribeStackResource : OK"

    def testDescribeStackResources(self):
        client = self.stack.get_heat_client()
        parameters = {'NameOrPid': self.stack.stackname,
            'LogicalResourceId': self.logical_resource_name}
        response = client.describe_stack_resources(**parameters)
        prefix = '/DescribeStackResourcesResponse/' +\
                'DescribeStackResourcesResult/StackResources/member'

        stack_id = self.stack.response_xml_item(response, prefix, "StackId")
        self.assertTrue(self.stack_id_re.match(stack_id) != None)

        resource_status = self.stack.response_xml_item(response, prefix,
                                                        "ResourceStatus")
        self.assertEqual(resource_status, self.logical_resource_status)

        resource_type = self.stack.response_xml_item(response, prefix,
                                                        "ResourceType")
        self.assertEqual(resource_type, self.logical_resource_type)

        update_time = self.stack.response_xml_item(response, prefix,
                                                   "Timestamp")
        self.assertTrue(self.time_re.match(update_time) != None)

        status_reason = self.stack.response_xml_item(response, prefix,
                                                      "ResourceStatusReason")
        self.assertEqual(status_reason, "None")

        stack_name = self.stack.response_xml_item(response, prefix,
                                                  "StackName")
        self.assertEqual(stack_name, self.stack.stackname)

        log_res_id = self.stack.response_xml_item(response, prefix,
                                                  "LogicalResourceId")
        self.assertEqual(log_res_id, self.logical_resource_name)

        phys_res_id = self.stack.response_xml_item(response, prefix,
                                                  "PhysicalResourceId")
        self.assertTrue(self.phys_res_id_re.match(phys_res_id) != None)

        print "DescribeStackResources : OK"

    def testListStackResources(self):
        client = self.stack.get_heat_client()
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = client.list_stack_resources(**parameters)
        prefix = '/ListStackResourcesResponse/ListStackResourcesResult' +\
               '/StackResourceSummaries/member'

        resource_status = self.stack.response_xml_item(response, prefix,
                                                        "ResourceStatus")
        self.assertEqual(resource_status, self.logical_resource_status)

        status_reason = self.stack.response_xml_item(response, prefix,
                                                      "ResourceStatusReason")
        self.assertEqual(status_reason, "None")

        update_time = self.stack.response_xml_item(response, prefix,
                                                   "LastUpdatedTimestamp")
        self.assertTrue(self.time_re.match(update_time) != None)

        resource_type = self.stack.response_xml_item(response, prefix,
                                                        "ResourceType")
        self.assertEqual(resource_type, self.logical_resource_type)

        log_res_id = self.stack.response_xml_item(response, prefix,
                                                  "LogicalResourceId")
        self.assertEqual(log_res_id, self.logical_resource_name)

        phys_res_id = self.stack.response_xml_item(response, prefix,
                                                  "PhysicalResourceId")
        self.assertTrue(self.phys_res_id_re.match(phys_res_id) != None)

        print "ListStackResources : OK"
