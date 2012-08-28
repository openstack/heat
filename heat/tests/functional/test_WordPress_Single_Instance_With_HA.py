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
import nose
from nose.plugins.attrib import attr
import unittest


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'HA'])
class HaFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance_With_HA.template'

        func_utils = util.FuncUtils()

        func_utils.prepare_jeos('F17', 'x86_64', 'cfntools')
        func_utils.create_stack(template, 'F17')
        func_utils.check_cfntools()
        func_utils.wait_for_provisioning()
        func_utils.check_user_data(template)

        self.ssh = func_utils.get_ssh_client()

    def service_is_running(self, name):
        stdin, stdout, sterr = \
                self.ssh.exec_command('sudo service status %s' % name)

        lines = stdout.readlines()
        for line in lines:
            if 'Active: active (running)' in line:
                return True
        return False

    def test_instance(self):

        # ensure wordpress was installed
        wp_file = '/etc/wordpress/wp-config.php'
        stdin, stdout, sterr = self.ssh.exec_command('ls ' + wp_file)
        result = stdout.readlines().pop().rstrip()
        self.assertEqual(result, wp_file)
        print "Wordpress installation detected"

        # check the httpd service is running
        self.assertTrue(self.service_is_running('httpd'))

        # kill httpd
        self.ssh.exec_command('sudo service stop httpd')

        # check that httpd service recovers
        # should take less than 60 seconds, but no worse than 70 seconds
        tries = 0
        while not self.service_is_running('httpd'):
            tries += 1
            self.assertTrue(tries < 8)
            time.sleep(10)

        func_utils.cleanup()
