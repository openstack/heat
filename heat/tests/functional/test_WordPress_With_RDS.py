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

import util
import verify
import nose
from nose.plugins.attrib import attr
import unittest


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'RDS'])
class WordPressRDSFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_With_RDS.template'
        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
            'DBUsername=dbuser',
            'DBPassword=' + os.environ['OS_PASSWORD']])

        self.func_utils = util.FuncUtils()

        self.func_utils.prepare_jeos('F17', 'x86_64', 'cfntools')
        self.func_utils.create_stack(template, 'F17')
        self.func_utils.check_cfntools()
        self.func_utils.wait_for_provisioning()
        self.func_utils.check_user_data(template)

        self.ssh = self.func_utils.get_ssh_client()

    def test_instance(self):
        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        wp_file = '/usr/share/wordpress/wp-config.php'
        stdin, stdout, sterr = self.ssh.exec_command('ls ' + wp_file)
        result = stdout.readlines().pop().rstrip()
        self.assertTrue(result == wp_file)
        print "Wordpress installation detected"

        # Check the DB_HOST value in the wordpress config is sane
        # ie not localhost, we don't have any way to get the IP of
        # the RDS nested-stack instance so we can't do a proper verification
        # Note there are two wp-config.php files, one under /etc and
        # one under /usr/share, the template only seds the RDS instance
        # IP into the /usr/share one, which seems to work but could be a
        # template bug..
        stdin, stdout, sterr = self.ssh.exec_command('grep DB_HOST ' + wp_file)
        result = stdout.readlines().pop().rstrip().split('\'')
        print "Checking wordpress DB_HOST, got %s" % result[3]
        self.assertTrue("localhost" != result[3])

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.func_utils.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))

        self.func_utils.cleanup()
