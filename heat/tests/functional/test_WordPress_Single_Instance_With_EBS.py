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

from heat.common import context
from heat.engine import manager
import unittest


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'ebs'])
class WordPressSingleEBSFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance_With_EBS.template'

        self.func_utils = util.FuncUtils()

        self.func_utils.prepare_jeos('F17', 'x86_64', 'cfntools')
        self.func_utils.create_stack(template, 'F17')
        self.func_utils.check_cfntools()
        self.func_utils.wait_for_provisioning()
        self.func_utils.check_user_data(template)

        self.ssh = self.func_utils.get_ssh_client()

    def test_instance(self):
        # 1. ensure wordpress was installed
        wp_file = '/etc/wordpress/wp-config.php'
        stdin, stdout, sterr = self.ssh.exec_command('ls ' + wp_file)
        result = stdout.readlines().pop().rstrip()
        self.assertEqual(result, wp_file)
        print "Wordpress installation detected"

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.func_utils.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))

        # Check EBS volume is present and mounted
        stdin, stdout, sterr = self.ssh.exec_command('grep vdc /proc/mounts')
        result = stdout.readlines().pop().rstrip()
        self.assertTrue(len(result))
        print "Checking EBS volume is attached : %s" % result
        devname = result.split()[0]
        self.assertEqual(devname, '/dev/vdc1')
        mountpoint = result.split()[1]
        self.assertEqual(mountpoint, '/var/lib/mysql')

        self.func_utils.cleanup()
