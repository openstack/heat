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
@attr(tag=['func', 'WordPress_Single_Instance_With_EBS_EIP.template', 'F17',
      'wordpress', 'ebs', 'eip'])
class WordPressEBSEIPFunctionalTest(unittest.TestCase):
    def setUp(self):
        template = 'WordPress_Single_Instance_With_EBS_EIP.template'

        stack_paramstr = ';'.join(['InstanceType=m1.xlarge',
            'DBUsername=dbuser',
            'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.Stack(template, 'F17', 'x86_64', 'cfntools',
            stack_paramstr)
        self.WikiServer = util.Instance('WikiServer')

    def tearDown(self):
        self.stack.cleanup()

    def test_instance(self):
        self.stack.create()
        self.WikiServer.wait_for_boot()
        self.WikiServer.check_cfntools()
        self.WikiServer.wait_for_provisioning()

        # ensure wordpress was installed
        self.assertTrue(self.WikiServer.file_present
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

        # Check EBS volume is present and mounted
        stdin, stdout, sterr = self.WikiServer.exec_command(
                                'grep vdc /proc/mounts')
        result = stdout.readlines().pop().rstrip()
        self.assertTrue(len(result))
        print "Checking EBS volume is attached : %s" % result
        devname = result.split()[0]
        self.assertEqual(devname, '/dev/vdc1')
        mountpoint = result.split()[1]
        self.assertEqual(mountpoint, '/var/lib/mysql')
