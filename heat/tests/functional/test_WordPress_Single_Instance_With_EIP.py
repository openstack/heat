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
@attr(tag=['func', 'wordpress', 'eip'])
class WordPressEIPFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance_With_EIP.template'

        self.stack = util.Stack(template, 'F17', 'x86_64', 'cfntools')
        self.WikiDatabase = util.Instance('WikiDatabase')
        self.WikiDatabase.check_cfntools()
        self.WikiDatabase.wait_for_provisioning()

    def test_instance(self):
        # ensure wordpress was installed
        self.assertTrue(self.WikiDatabase.file_present
                        ('/etc/wordpress/wp-config.php'))
        print "Wordpress installation detected"

        # 2. check floating ip assignment
        nclient = self.stack.get_nova_client()
        if len(nclient.floating_ips.list()) == 0:
            print 'zero floating IPs detected'
            self.assertTrue(False)
        else:
            found = 0
            mylist = nclient.floating_ips.list()
            for item in mylist:
                if item.instance_id == self.stack.phys_rec_id:
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

        self.stack.cleanup()
