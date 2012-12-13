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
@attr(tag=['func', 'wordpress', 'F17',
           'WordPress_Single_Instance.template', 'boto'])
class WordPressBotoFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance.template'

        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
            'DBUsername=dbuser',
            'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.StackBoto(self, template,
                                    'F17', 'x86_64', 'cfntools',
                                    stack_paramstr)
        self.WikiDatabase = util.Instance(self, 'WikiDatabase')

    def tearDown(self):
        self.stack.cleanup()

    def test_instance(self):
        self.stack.create()

        self.WikiDatabase.wait_for_boot()
        self.WikiDatabase.check_cfntools()
        self.WikiDatabase.wait_for_provisioning()

        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        self.assertTrue(self.WikiDatabase.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected"

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.stack.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))
