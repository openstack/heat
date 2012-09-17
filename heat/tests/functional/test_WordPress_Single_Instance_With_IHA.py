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
import nose
from nose.plugins.attrib import attr
import unittest
import time


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'HA',
      'WordPress_Single_Instance_With_IHA.template'])
class WordPressIHAFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance_With_IHA.template'
        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
            'DBUsername=dbuser',
            'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.Stack(template, 'F17', 'x86_64', 'cfntools',
            stack_paramstr)
        self.WikiDatabase = util.Instance('WikiDatabase')

    def tearDown(self):
        self.stack.cleanup()

    def test_instance(self):
        self.stack.create()
        self.WikiDatabase.wait_for_boot()
        self.WikiDatabase.check_cfntools()
        self.WikiDatabase.wait_for_provisioning()

        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        wp_file = '/usr/share/wordpress/wp-config.php'
        self.assertTrue(self.WikiDatabase.file_present(wp_file))
        print "Wordpress installation detected"

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.stack.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))

        # Save the instance physical resource ID
        phys_res_ids = self.stack.instance_phys_ids()
        self.assertEqual(len(phys_res_ids), 1)
        print "Shutting down instance ID = %s" % phys_res_ids[0]

        # Now shut down the instance via SSH, and wait for HA to reprovision
        # note it may not come back on the same IP
        stdin, stdout, stderr =\
            self.WikiDatabase.get_ssh_client().exec_command('sudo /sbin/halt')

        # Now poll the stack events, as the current WikiDatabase instance
        # should be replaced with a new one
        # we can then prove the physical resource ID is different, and that
        # wordpress is accessible on the new WikiDatabase instance
        tries = 0
        while (tries <= 500):
                pollids = self.stack.instance_phys_ids()
                if (len(pollids) == 2):
                    self.assertTrue(pollids[1] != phys_res_ids[0])
                    print "Instance replaced, new ID = %s" % pollids[1]
                    break
                time.sleep(10)
                tries += 1

        # Check we didn't timeout
        self.assertTrue(tries < 500)

        # Create a new Instance object and wait for boot
        self.WikiDatabaseNew = util.Instance('WikiDatabase')
        self.WikiDatabaseNew.wait_for_boot()
        self.WikiDatabaseNew.check_cfntools()
        self.WikiDatabaseNew.wait_for_provisioning()

        # Re-check wordpress installation as for the first instance
        self.assertTrue(self.WikiDatabaseNew.file_present(wp_file))
        print "Wordpress installation detected on new instance"

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.stack.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        self.assertTrue(ver.verify_wordpress(stack_url))
