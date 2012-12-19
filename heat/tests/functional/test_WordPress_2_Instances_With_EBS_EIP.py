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
from nose.plugins.attrib import attr
import unittest
import os


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'eip', 'ebs', 'F17'])
class WordPress2EBSEIPFunctionalTest(unittest.TestCase):
    def setUp(self):
        self.template = 'WordPress_2_Instances_With_EBS_EIP.template'

        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
                                   'DBUsername=dbuser',
                                   'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.Stack(self, self.template,
                                'F17', 'x86_64', 'cfntools',
                                stack_paramstr)

        self.webserver = util.Instance(self, 'WebServer')

        self.database = util.Instance(self, 'WikiDatabase')

    def tearDown(self):
        self.stack.cleanup()

    def test_instance(self):
        self.stack.create()

        self.webserver.wait_for_boot()
        self.webserver.check_cfntools()
        self.webserver.wait_for_provisioning()
        self.webserver.check_user_data(self.template)

        self.database.wait_for_boot()
        self.database.check_cfntools()
        self.database.wait_for_provisioning()
        self.database.check_user_data(self.template)

        # Check wordpress installation
        wp_config_file = '/etc/wordpress/wp-config.php'
        self.assertTrue(self.webserver.file_present(wp_config_file),
                        'wp-config.php is not present')

        # Check mysql is installed and running
        stdin, stdout, sterr = self.database.exec_command(
            'systemctl status mysqld.service')
        result = stdout.read()
        self.assertTrue('running' in result, 'mysql service is not running')

        # Check EBS volume is present and mounted
        stdin, stdout, sterr = self.database.exec_command(
            'grep vdc /proc/mounts')
        lines = stdout.readlines()
        self.assertTrue(len(lines) > 0)
        result = lines.pop().strip()
        self.assertTrue(len(result) > 0)
        print "Checking EBS volume is attached: %s" % result
        self.assertTrue('/dev/vdc1' in result)
        self.assertTrue('/var/lib/mysql' in result)

        # Check the floating IPs
        self.assertTrue(
            self.webserver.floating_ip_present(),
            'WebServer instance does not have a floating IP assigned')
        self.assertTrue(
            self.database.floating_ip_present(),
            'WikiDatabase instance does not have a floating IP assigned')

        # Check wordpress is running and acessible at the correct URL
        stack_url = self.stack.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(
            ver.verify_wordpress(stack_url),
            'Wordpress is not accessible at: %s' % stack_url)
