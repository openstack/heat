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
from nose.plugins.attrib import attr
import unittest


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'api', 'cfn', 'F17'])
class CfnApiUpdateStackFunctionalTest(unittest.TestCase):
    '''
    This test launches a wordpress stack then attempts to verify
    correct operation of all the heat CFN API UpdateStack action

    This is a separate test from the main CfnApiFunctionalTest
    because part of the test replaces the instance, making it
    quite hard to avoid breaking things for the other tests
    '''
    @classmethod
    def setupAll(cls):
        print "SETUPALL"
        template = 'WordPress_Single_Instance.template'

        cls.instance_type = 'm1.xlarge'
        cls.db_user = 'dbuser'
        cls.stack_paramstr = ';'.join(['InstanceType=%s' % cls.instance_type,
                                       'DBUsername=%s' % cls.db_user,
                                       'DBPassword=' +
                                       os.environ['OS_PASSWORD']])

        cls.logical_resource_name = 'WikiDatabase'
        cls.logical_resource_type = 'AWS::EC2::Instance'

        # Just to get the assert*() methods
        class CfnApiFunctions(unittest.TestCase):
            @unittest.skip('Not a real test case')
            def runTest(self):
                pass

        cls.inst = CfnApiFunctions()
        cls.stack = util.Stack(cls.inst, template, 'F17', 'x86_64', 'cfntools',
                               cls.stack_paramstr)
        cls.WikiDatabase = util.Instance(cls.inst, cls.logical_resource_name)

        try:
            cls.stack.create()
            cls.WikiDatabase.wait_for_boot()
            cls.WikiDatabase.check_cfntools()
            cls.WikiDatabase.wait_for_provisioning()
            cls.logical_resource_status = "CREATE_COMPLETE"
            cls.stack_status = "CREATE_COMPLETE"
        except Exception as ex:
            print "setupAll failed : %s" % ex
            cls.stack.cleanup()
            raise

    @classmethod
    def teardownAll(cls):
        print "TEARDOWNALL"
        cls.stack.cleanup()

    def testUpdateStack(self):
        # If we just update without changing the parameters
        # this should result in the stack going to UPDATE_COMPLETE
        # without replacing the instance

        physids = self.stack.instance_phys_ids()
        self.assertEqual(len(physids), 1)
        print "UPDATE start, instance IDs = %s" % physids

        self.stack.update()
        self.logical_resource_status = "UPDATE_COMPLETE"
        self.stack_status = "UPDATE_COMPLETE"
        self.stack_status_reason = "Stack successfully updated"

        updpids = self.stack.instance_phys_ids()
        self.assertEqual(len(updpids), 1)
        print "UPDATE complete, instance IDs = %s" % updpids

        self.assertEqual(updpids[0], physids[0])
        print "UpdateStack : OK"

    def testUpdateStackReplace(self):
        # Then if we change a template parameter, instance should get replaced
        physids = self.stack.instance_phys_ids()
        self.assertEqual(len(physids), 1)
        print "UPDATE start, instance IDs = %s" % physids

        self.db_user = 'anewuser'
        self.stack_paramstr = ';'.join(['InstanceType=%s' % self.instance_type,
                                        'DBUsername=%s' % self.db_user,
                                        'DBPassword=' +
                                        os.environ['OS_PASSWORD']])
        self.stack.stack_paramstr = self.stack_paramstr
        self.stack.update()
        tries = 0
        while (tries <= 500):
                pollids = self.stack.instance_phys_ids()
                print "Waiting for Instance to be replaced %s/%s %s" %\
                      (tries, 500, pollids)
                if (len(pollids) == 2):
                    self.assertTrue(pollids[1] != physids[0])
                    print "Instance replaced, new ID = %s" % pollids[1]
                    break
                time.sleep(10)
                tries += 1

        # Check we didn't timeout
        self.assertTrue(tries < 500)

        # Now use DescribeStacks to check the parameter is updated
        parameters = {}
        parameters['StackName'] = self.stack.stackname
        response = self.stack.heatclient.describe_stacks(**parameters)
        prefix = '/DescribeStacksResponse/DescribeStacksResult/Stacks/member'
        # value for each key, then check the extracted value
        param_prefix = prefix + '/Parameters/member[ParameterKey="DBUsername"]'
        lookup_value = self.stack.response_xml_item(response, param_prefix,
                                                    "ParameterValue")
        print "Updated, got DBUsername=%s" % lookup_value
        self.assertEqual(lookup_value, self.db_user)

        # Now we have to Create a new Instance object and wait for
        # provisioning to be complete, or the next test will fail
        self.WikiDatabase = util.Instance(self.inst,
                                          self.logical_resource_name)
        self.WikiDatabase.wait_for_boot()
        self.WikiDatabase.check_cfntools()
        self.WikiDatabase.wait_for_provisioning()
        print "Update completed, instance rebuild complete"

        self.assertTrue(self.WikiDatabase.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected after update"

        print "UpdateStack (Replace) : OK"
