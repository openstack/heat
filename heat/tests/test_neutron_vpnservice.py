# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
#    under the License.

import copy

from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import scheduler
from heat.engine.resources.neutron import vpnservice
from heat.openstack.common.importutils import try_import
from heat.tests import fakes
from heat.tests import utils
from heat.tests.common import HeatTestCase


neutronclient = try_import('neutronclient.v2_0.client')

vpnservice_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test VPN service resource",
  "Parameters" : {},
  "Resources" : {
    "VPNService" : {
      "Type" : "OS::Neutron::VPNService",
      "Properties" : {
        "name" : "VPNService",
        "description" : "My new VPN service",
        "admin_state_up" : true,
        "router_id" : "rou123",
        "subnet_id" : "sub123"
      }
    }
  }
}
'''

ikepolicy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test IKE policy resource",
  "Parameters" : {},
  "Resources" : {
    "IKEPolicy" : {
      "Type" : "OS::Neutron::IKEPolicy",
      "Properties" : {
        "name" : "IKEPolicy",
        "description" : "My new IKE policy",
        "auth_algorithm" : "sha1",
        "encryption_algorithm" : "3des",
        "phase1_negotiation_mode" : "main",
        "lifetime" : {
            "units" : "seconds",
            "value" : 3600
        },
        "pfs" : "group5",
        "ike_version" : "v1"
      }
    }
  }
}
'''


@skipIf(neutronclient is None, 'neutronclient unavailable')
class VPNServiceTest(HeatTestCase):

    VPN_SERVICE_CONF = {
        'vpnservice': {
            'name': 'VPNService',
            'description': 'My new VPN service',
            'admin_state_up': True,
            'router_id': 'rou123',
            'subnet_id': 'sub123'
        }
    }

    def setUp(self):
        super(VPNServiceTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_vpnservice')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_vpnservice')
        self.m.StubOutWithMock(neutronclient.Client, 'show_vpnservice')
        self.m.StubOutWithMock(neutronclient.Client, 'update_vpnservice')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_vpnservice(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_vpnservice(
            self.VPN_SERVICE_CONF).AndReturn({'vpnservice': {'id': 'vpn123'}})
        snippet = template_format.parse(vpnservice_template)
        self.stack = utils.parse_stack(snippet)
        return vpnservice.VPNService('vpnservice',
                                     snippet['Resources']['VPNService'],
                                     self.stack)

    @utils.stack_delete_after
    def test_create(self):
        rsrc = self.create_vpnservice()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_create_failed(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_vpnservice(self.VPN_SERVICE_CONF).AndRaise(
            vpnservice.NeutronClientException())
        self.m.ReplayAll()
        snippet = template_format.parse(vpnservice_template)
        self.stack = utils.parse_stack(snippet)
        rsrc = vpnservice.VPNService('vpnservice',
                                     snippet['Resources']['VPNService'],
                                     self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete(self):
        neutronclient.Client.delete_vpnservice('vpn123')
        neutronclient.Client.show_vpnservice('vpn123').AndRaise(
            vpnservice.NeutronClientException(status_code=404))
        rsrc = self.create_vpnservice()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete_already_gone(self):
        neutronclient.Client.delete_vpnservice('vpn123').AndRaise(
            vpnservice.NeutronClientException(status_code=404))
        rsrc = self.create_vpnservice()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete_failed(self):
        neutronclient.Client.delete_vpnservice('vpn123').AndRaise(
            vpnservice.NeutronClientException(status_code=400))
        rsrc = self.create_vpnservice()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_attribute(self):
        rsrc = self.create_vpnservice()
        neutronclient.Client.show_vpnservice('vpn123').MultipleTimes(
        ).AndReturn(self.VPN_SERVICE_CONF)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('VPNService', rsrc.FnGetAtt('name'))
        self.assertEqual('My new VPN service', rsrc.FnGetAtt('description'))
        self.assertEqual(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual('rou123', rsrc.FnGetAtt('router_id'))
        self.assertEqual('sub123', rsrc.FnGetAtt('subnet_id'))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_attribute_failed(self):
        rsrc = self.create_vpnservice()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'non-existent_property')
        self.assertEqual(
            'The Referenced Attribute (vpnservice non-existent_property) is '
            'incorrect.',
            str(error))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update(self):
        rsrc = self.create_vpnservice()
        neutronclient.Client.update_vpnservice(
            'vpn123', {'vpnservice': {'admin_state_up': False}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['admin_state_up'] = False
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.m.VerifyAll()


@skipIf(neutronclient is None, 'neutronclient unavailable')
class IKEPolicyTest(HeatTestCase):

    IKE_POLICY_CONF = {
        'ikepolicy': {
            'name': 'IKEPolicy',
            'description': 'My new IKE policy',
            'auth_algorithm': 'sha1',
            'encryption_algorithm': '3des',
            'phase1_negotiation_mode': 'main',
            'lifetime': {
                'units': 'seconds',
                'value': 3600
            },
            'pfs': 'group5',
            'ike_version': 'v1'
        }
    }

    def setUp(self):
        super(IKEPolicyTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_ikepolicy')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_ikepolicy')
        self.m.StubOutWithMock(neutronclient.Client, 'show_ikepolicy')
        self.m.StubOutWithMock(neutronclient.Client, 'update_ikepolicy')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_ikepolicy(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_ikepolicy(
            self.IKE_POLICY_CONF).AndReturn(
                {'ikepolicy': {'id': 'ike123'}})
        snippet = template_format.parse(ikepolicy_template)
        self.stack = utils.parse_stack(snippet)
        return vpnservice.IKEPolicy('ikepolicy',
                                    snippet['Resources']['IKEPolicy'],
                                    self.stack)

    @utils.stack_delete_after
    def test_create(self):
        rsrc = self.create_ikepolicy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_create_failed(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_ikepolicy(
            self.IKE_POLICY_CONF).AndRaise(
                vpnservice.NeutronClientException())
        self.m.ReplayAll()
        snippet = template_format.parse(ikepolicy_template)
        self.stack = utils.parse_stack(snippet)
        rsrc = vpnservice.IKEPolicy(
            'ikepolicy',
            snippet['Resources']['IKEPolicy'],
            self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete(self):
        neutronclient.Client.delete_ikepolicy('ike123')
        neutronclient.Client.show_ikepolicy('ike123').AndRaise(
            vpnservice.NeutronClientException(status_code=404))
        rsrc = self.create_ikepolicy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete_already_gone(self):
        neutronclient.Client.delete_ikepolicy('ike123').AndRaise(
            vpnservice.NeutronClientException(status_code=404))
        rsrc = self.create_ikepolicy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete_failed(self):
        neutronclient.Client.delete_ikepolicy('ike123').AndRaise(
            vpnservice.NeutronClientException(status_code=400))
        rsrc = self.create_ikepolicy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            str(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_attribute(self):
        rsrc = self.create_ikepolicy()
        neutronclient.Client.show_ikepolicy(
            'ike123').MultipleTimes().AndReturn(self.IKE_POLICY_CONF)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('IKEPolicy', rsrc.FnGetAtt('name'))
        self.assertEqual('My new IKE policy', rsrc.FnGetAtt('description'))
        self.assertEqual('sha1', rsrc.FnGetAtt('auth_algorithm'))
        self.assertEqual('3des', rsrc.FnGetAtt('encryption_algorithm'))
        self.assertEqual('main', rsrc.FnGetAtt('phase1_negotiation_mode'))
        self.assertEqual('seconds', rsrc.FnGetAtt('lifetime')['units'])
        self.assertEqual(3600, rsrc.FnGetAtt('lifetime')['value'])
        self.assertEqual('group5', rsrc.FnGetAtt('pfs'))
        self.assertEqual('v1', rsrc.FnGetAtt('ike_version'))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_attribute_failed(self):
        rsrc = self.create_ikepolicy()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'non-existent_property')
        self.assertEqual(
            'The Referenced Attribute (ikepolicy non-existent_property) is '
            'incorrect.',
            str(error))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update(self):
        rsrc = self.create_ikepolicy()
        neutronclient.Client.update_ikepolicy('ike123',
                                              {'ikepolicy': {
                                                  'name': 'New IKEPolicy'}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = 'New IKEPolicy'
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.m.VerifyAll()
