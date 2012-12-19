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
@attr(tag=['func', 'wordpress', 'haproxy', 'F17',
           'HAProxy_Single_Instance.template'])
class HAProxyFunctionalTest(unittest.TestCase):
    def setUp(self):
        # The HAProxy template somewhat un-usefully load-balances a single
        # server, so we launch a wordpress stack and stick haproxy in front
        wp_template = 'WordPress_Single_Instance.template'

        wp_paramstr = ';'.join(['InstanceType=m1.xlarge',
                                'DBUsername=dbuser',
                                'DBPassword=' + os.environ['OS_PASSWORD']])

        self.stack = util.Stack(self, wp_template, 'F17', 'x86_64', 'cfntools',
                                wp_paramstr)
        self.WikiDatabase = util.Instance(self, 'WikiDatabase')

        self.hap_stack = None

    def tearDown(self):
        self.stack.cleanup()
        if self.hap_stack:
            self.hap_stack.cleanup()

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

        # So wordpress instance is up, we now launch the HAProxy instance
        # and prove wordpress is accessable via the proxy instance IP
        hap_stackname = 'hap_teststack'
        hap_template = 'HAProxy_Single_Instance.template'
        hap_paramstr = ';'.join(['InstanceType=m1.xlarge',
                       "Server1=%s:80" % self.WikiDatabase.ip])

        self.hap_stack = util.Stack(self, hap_template,
                                    'F17', 'x86_64', 'cfntools',
                                    hap_paramstr, stackname=hap_stackname)
        self.LoadBalancerInstance = util.Instance(self, 'LoadBalancerInstance',
                                                  hap_stackname)
        self.hap_stack.create()
        self.LoadBalancerInstance.wait_for_boot()
        self.LoadBalancerInstance.check_cfntools()
        self.LoadBalancerInstance.wait_for_provisioning()

        # Verify the output URL parses as expected, ie check that
        # the wordpress installation is operational via the proxy
        proxy_ip = self.hap_stack.get_stack_output("PublicIp")
        print "Got haproxy stack output PublicIp=%s, verifying" % proxy_ip
        proxy_url = "http://%s/wordpress" % proxy_ip
        self.assertTrue(ver.verify_wordpress(proxy_url))
