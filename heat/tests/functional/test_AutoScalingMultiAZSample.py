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
import os
from time import sleep


@attr(speed='slow')
@attr(tag=['func', 'autoscaling', 'AutoScalingMultiAZSample.template'])
class AutoScalingMultiAZSampleFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'AutoScalingMultiAZSample.template'

        stack_paramstr = ';'.join(['InstanceType=m1.small',
                         'DBUsername=dbuser',
                         'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.Stack(template, 'F17', 'x86_64', 'cfntools',
            stack_paramstr)
        self.WebServerGroup0 = util.Instance('WebServerGroup-0')

    def tearDown(self):
        pass
        self.stack.cleanup()

    def test_instance(self):
        self.stack.create()
        self.WebServerGroup0.wait_for_boot()
        self.WebServerGroup0.check_cfntools()
        self.WebServerGroup0.wait_for_provisioning()

        # TODO: verify the code below tests the template properly

# TODO(sdake) use a util exists function for nonexistent instances (needs dev)
        # Trigger the load balancer by taking up memory
        self.WebServerGroup0.exec_command('memhog -r100000 1500m')

        # Give the load balancer 2 minutes to react
        sleep(2 * 60)

        self.WebServerGroup1 = util.Instance('WebServerGroup-1')
        # Verify the second instance gets launched
        self.assertTrue(self.WebServerGroup1.exists())
        self.WebServerGroup1.wait_for_boot()
        self.WebServerGroup1.check_cfntools()
        self.WebServerGroup1.wait_for_provisioning()

        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        self.assertTrue(self.WebServerGroup0.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected on WSG0"

        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        self.assertTrue(self.WebServerGroup1.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected on WSG1"

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        stack_url = self.stack.get_stack_output("URL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))
