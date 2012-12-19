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
from nose.plugins.attrib import attr
import unittest


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'RDS', 'F17',
      'WordPress_With_RDS.template'])
class WordPressRDSFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_With_RDS.template'
        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
                                   'DBUsername=dbuser',
                                   'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.Stack(self, template, 'F17', 'x86_64', 'cfntools',
                                stack_paramstr)
        self.WebServer = util.Instance(self, 'WebServer')

    def tearDown(self):
        self.stack.cleanup()

    def test_instance(self):
        self.stack.create()
        self.WebServer.wait_for_boot()
        self.WebServer.check_cfntools()
        self.WebServer.wait_for_provisioning()

        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        wp_file = '/usr/share/wordpress/wp-config.php'
        self.assertTrue(self.WebServer.file_present(wp_file))
        print "Wordpress installation detected"

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.stack.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))

        # Check the DB_HOST value in the wordpress config is sane
        # ie not localhost, we don't have any way to get the IP of
        # the RDS nested-stack instance so we can't do a proper verification
        # Note there are two wp-config.php files, one under /etc and
        # one under /usr/share, the template only seds the RDS instance
        # IP into the /usr/share one, which seems to work but could be a
        # template bug..
        stdin, stdout, sterr =\
            self.WebServer.get_ssh_client().exec_command('grep DB_HOST '
                                                         + wp_file)
        result = stdout.readlines().pop().rstrip().split('\'')
        print "Checking wordpress DB_HOST, got %s" % result[3]
        self.assertTrue("localhost" != result[3])
