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
import os
import time


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'HA', 'F17',
      'WordPress_Single_Instance_With_HA.template'])
class HaFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance_With_HA.template'

        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
            'DBUsername=dbuser',
            'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.Stack(self, template, 'F17', 'x86_64', 'cfntools',
            stack_paramstr)
        self.WikiDatabase = util.Instance(self, 'WikiDatabase')

    def tearDown(self):
        self.stack.cleanup()

    def service_is_running(self, name):
        stdin, stdout, sterr = \
            self.WikiDatabase.exec_command(
                'systemctl status %s' % name + '.service')

        lines = stdout.readlines()
        for line in lines:
            if 'Active: active (running)' in line:
                return True
        return False

    def test_instance(self):
        self.stack.create()
        self.WikiDatabase.wait_for_boot()
        self.WikiDatabase.check_cfntools()
        self.WikiDatabase.wait_for_provisioning()

        # ensure wordpress was installed
        self.assertTrue(self.WikiDatabase.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected"

        # check the httpd service is running
        self.assertTrue(self.service_is_running('httpd'))

        # kill httpd
        self.WikiDatabase.exec_sudo_command('systemctl stop httpd.service')

        # check that httpd service recovers
        # should take less than 60 seconds, but no worse than 70 seconds
        tries = 0
        while not self.service_is_running('httpd'):
            tries += 1
            self.assertTrue(tries < 8)
            time.sleep(10)
