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


@attr(speed='slow')
@attr(tag=['func', 'openshift', 'F16-openshift',
           'OpenShift_Prebuilt_JEOS.template'])
class OpenShiftFunctionalTest(unittest.TestCase):

    def tearDown(self):
        self.stack.cleanup()

    def setUp(self):
        template = 'OpenShift_Prebuilt_JEOS.template'
        stack_paramstr = ';'.join(['InstanceType=m1.xlarge'])

        self.stack = util.Stack(self, template, 'F16', 'x86_64',
                'cfntools-openshift', stack_paramstr)

        self.Node = util.Instance(self, 'OpenShiftNodeServer')
        self.Broker = util.Instance(self, 'OpenShiftBrokerServer')

    def test_instance(self):
        self.stack.create()
        self.Broker.wait_for_boot()
        self.Node.wait_for_boot()
        self.Node.check_cfntools()
        self.Broker.check_cfntools()
        self.Node.wait_for_provisioning()
        self.Broker.wait_for_provisioning()

        # ensure wordpress was installed by checking for expected
        # configuration file over ssh
        self.assertTrue(self.Broker.file_present
                        ('/etc/sysconfig/stickshift-broker'))
        print 'OpenShift installation detected'

        # must change ip lookup so apache rewrite works properly
        openshift_host = 'hello-admin.example.com'
        util.add_host(self.Broker.ip, openshift_host)

        # Verify the output URL parses as expected, ie check that
        # the openshift installation is operational with the deployed hello app
        stack_url = 'https://' + openshift_host
        print 'Verifying URL=%s' % stack_url
        ver = verify.VerifyStack()
        self.assertTrue(ver.verify_openshift(stack_url))

        util.remove_host(self.Broker.ip, openshift_host)
