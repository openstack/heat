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
import os


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'eip', 'F17',
      'WordPress_Single_Instance_With_EIP.template'])
class WordPressEIPFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance_With_EIP.template'

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

        # ensure wordpress was installed
        self.assertTrue(self.WebServer.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected"

        # 2. check floating ip assignment
        if len(self.stack.novaclient.floating_ips.list()) == 0:
            print 'zero floating IPs detected'
            self.assertTrue(False)
        else:
            found = 0
            mylist = self.stack.novaclient.floating_ips.list()
            for item in mylist:
                if item.instance_id == self.stack.instance_phys_ids()[0]:
                    print 'floating IP found', item.ip
                    found = 1
                    break
            self.assertEqual(found, 1)

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational
        # Note that the WebsiteURL uses the non-EIP address
        stack_url = self.stack.get_stack_output("WebsiteURL")
        print "Got stack output WebsiteURL=%s, verifying" % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_wordpress(stack_url))

        # Then the InstanceIPAddress is the EIP address
        # which should also render the wordpress page
        stack_eip = self.stack.get_stack_output("InstanceIPAddress")
        eip_url = "http://%s/wordpress" % stack_eip
        print "Got stack output InstanceIPAddress=%s, verifying url %s" %\
              (stack_eip, eip_url)
        self.assertTrue(ver.verify_wordpress(eip_url))
