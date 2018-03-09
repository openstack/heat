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
#    under the License.

import copy
import mock
import six

from neutronclient.common import exceptions
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient
from oslo_config import cfg

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import vpnservice
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


vpnservice_template = '''
heat_template_version: 2015-04-30
description: Template to test vpnservice Neutron resource
resources:
  VPNService:
    type: OS::Neutron::VPNService
    properties:
      name: VPNService
      description: My new VPN service
      admin_state_up: true
      router_id: rou123
      subnet: sub123
'''

vpnservice_template_deprecated = vpnservice_template.replace(
    'subnet', 'subnet_id')

ipsec_site_connection_template = '''
heat_template_version: 2015-04-30
description: Template to test IPsec policy resource
resources:
  IPsecSiteConnection:
    type: OS::Neutron::IPsecSiteConnection,
    properties:
      name: IPsecSiteConnection
      description: My new VPN connection
      peer_address: 172.24.4.233
      peer_id: 172.24.4.233
      peer_cidrs: [ 10.2.0.0/24 ]
      mtu: 1500
      dpd:
        actions: hold
        interval: 30
        timeout: 120
      psk: secret
      initiator: bi-directional
      admin_state_up: true
      ikepolicy_id: ike123
      ipsecpolicy_id: ips123
      vpnservice_id: vpn123
'''

ikepolicy_template = '''
heat_template_version: 2015-04-30
description: Template to test IKE policy resource
resources:
  IKEPolicy:
    type: OS::Neutron::IKEPolicy
    properties:
      name: IKEPolicy
      description: My new IKE policy
      auth_algorithm: sha1
      encryption_algorithm: 3des
      phase1_negotiation_mode: main
      lifetime:
        units: seconds
        value: 3600
      pfs: group5
      ike_version: v1
'''

ipsecpolicy_template = '''
heat_template_version: 2015-04-30
description: Template to test IPsec policy resource
resources:
  IPsecPolicy:
    type: OS::Neutron::IPsecPolicy
    properties:
      name: IPsecPolicy
      description: My new IPsec policy
      transform_protocol: esp
      encapsulation_mode: tunnel
      auth_algorithm: sha1
      encryption_algorithm: 3des
      lifetime:
        units: seconds
        value: 3600
      pfs : group5
'''


class VPNServiceTest(common.HeatTestCase):

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
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        def lookup(client, lookup_type, name, cmd_resource):
            return name

        self.patchobject(neutronV20,
                         'find_resourceid_by_name_or_id',
                         side_effect=lookup)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_vpnservice(self, resolve_neutron=True, resolve_router=True):
        self.stub_SubnetConstraint_validate()
        self.stub_RouterConstraint_validate()
        if resolve_neutron:
            snippet = template_format.parse(vpnservice_template)
        else:
            snippet = template_format.parse(vpnservice_template_deprecated)
        if resolve_router:
            props = snippet['resources']['VPNService']['properties']
            props['router'] = 'rou123'
            del props['router_id']
        self.mockclient.create_vpnservice.return_value = {
            'vpnservice': {'id': 'vpn123'}
        }
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return vpnservice.VPNService('vpnservice',
                                     resource_defns['VPNService'],
                                     self.stack)

    def test_create_deprecated(self):
        self._test_create(resolve_neutron=False)

    def test_create(self):
        self._test_create()

    def test_create_router_id(self):
        self._test_create(resolve_router=False)

    def _test_create(self, resolve_neutron=True, resolve_router=True):
        rsrc = self.create_vpnservice(resolve_neutron, resolve_router)
        self.mockclient.show_vpnservice.return_value = {
            'vpnservice': {'status': 'ACTIVE'}
        }
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        # Ensure that property translates
        if not resolve_router:
            self.assertEqual('rou123', rsrc.properties.get(rsrc.ROUTER))
            self.assertIsNone(rsrc.properties.get(rsrc.ROUTER_ID))

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.show_vpnservice.assert_called_once_with('vpn123')

    def test_create_failed_error_status(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        rsrc = self.create_vpnservice()

        self.mockclient.show_vpnservice.side_effect = [
            {'vpnservice': {'status': 'PENDING_CREATE'}},
            {'vpnservice': {'status': 'ERROR'}},
        ]

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'ResourceInError: resources.vpnservice: '
            'Went to status ERROR due to "Error in VPNService"',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.show_vpnservice.assert_called_with('vpn123')

    def test_create_failed(self):
        self.stub_RouterConstraint_validate()

        self.mockclient.create_vpnservice.side_effect = (
            exceptions.NeutronClientException)

        snippet = template_format.parse(vpnservice_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = vpnservice.VPNService('vpnservice',
                                     resource_defns['VPNService'],
                                     self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.vpnservice: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)

    def test_delete(self):
        rsrc = self.create_vpnservice()
        self.mockclient.show_vpnservice.side_effect = [
            {'vpnservice': {'status': 'ACTIVE'}},
            exceptions.NeutronClientException(status_code=404),
        ]
        self.mockclient.delete_vpnservice.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.delete_vpnservice.assert_called_once_with(
            'vpn123')
        self.mockclient.show_vpnservice.assert_called_with('vpn123')
        self.assertEqual(2, self.mockclient.show_vpnservice.call_count)

    def test_delete_already_gone(self):
        rsrc = self.create_vpnservice()
        self.mockclient.show_vpnservice.return_value = {
            'vpnservice': {'status': 'ACTIVE'}
        }
        self.mockclient.delete_vpnservice.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.show_vpnservice.assert_called_once_with('vpn123')
        self.mockclient.delete_vpnservice.assert_called_once_with(
            'vpn123')

    def test_delete_failed(self):
        rsrc = self.create_vpnservice()
        self.mockclient.show_vpnservice.return_value = {
            'vpnservice': {'status': 'ACTIVE'}
        }
        self.mockclient.delete_vpnservice.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.vpnservice: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.show_vpnservice.assert_called_once_with('vpn123')
        self.mockclient.delete_vpnservice.assert_called_once_with(
            'vpn123')

    def test_attribute(self):
        rsrc = self.create_vpnservice()
        self.mockclient.show_vpnservice.return_value = {
            'vpnservice': {'status': 'ACTIVE'}
        }

        scheduler.TaskRunner(rsrc.create)()

        self.mockclient.show_vpnservice.return_value = self.VPN_SERVICE_CONF

        self.assertEqual('VPNService', rsrc.FnGetAtt('name'))
        self.assertEqual('My new VPN service', rsrc.FnGetAtt('description'))
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual('rou123', rsrc.FnGetAtt('router_id'))
        self.assertEqual('sub123', rsrc.FnGetAtt('subnet_id'))

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.show_vpnservice.assert_called_with('vpn123')

    def test_attribute_failed(self):
        rsrc = self.create_vpnservice()
        self.mockclient.show_vpnservice.return_value = {
            'vpnservice': {'status': 'ACTIVE'}
        }

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'non-existent_property')
        self.assertEqual(
            'The Referenced Attribute (vpnservice non-existent_property) is '
            'incorrect.',
            six.text_type(error))

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.show_vpnservice.assert_called_once_with('vpn123')

    def test_update(self):
        rsrc = self.create_vpnservice()
        self.mockclient.show_vpnservice.return_value = {
            'vpnservice': {'status': 'ACTIVE'}
        }
        self.mockclient.update_vpnservice.return_value = None

        rsrc.physical_resource_name = mock.Mock(return_value='VPNService')

        scheduler.TaskRunner(rsrc.create)()
        # with name
        prop_diff = {'name': 'VPNService', 'admin_state_up': False}
        self.assertIsNone(rsrc.handle_update({}, {}, prop_diff))

        # without name
        prop_diff = {'name': None, 'admin_state_up': False}
        self.assertIsNone(rsrc.handle_update({}, {}, prop_diff))

        self.mockclient.create_vpnservice.assert_called_once_with(
            self.VPN_SERVICE_CONF)
        self.mockclient.show_vpnservice.assert_called_once_with('vpn123')
        upd_dict = {'vpnservice': {'name': 'VPNService',
                                   'admin_state_up': False}}
        self.mockclient.update_vpnservice.assert_called_with('vpn123',
                                                             upd_dict)


class IPsecSiteConnectionTest(common.HeatTestCase):

    IPSEC_SITE_CONNECTION_CONF = {
        'ipsec_site_connection': {
            'name': 'IPsecSiteConnection',
            'description': 'My new VPN connection',
            'peer_address': '172.24.4.233',
            'peer_id': '172.24.4.233',
            'peer_cidrs': ['10.2.0.0/24'],
            'mtu': 1500,
            'dpd': {
                'actions': 'hold',
                'interval': 30,
                'timeout': 120
            },
            'psk': 'secret',
            'initiator': 'bi-directional',
            'admin_state_up': True,
            'ikepolicy_id': 'ike123',
            'ipsecpolicy_id': 'ips123',
            'vpnservice_id': 'vpn123'
        }
    }

    def setUp(self):
        super(IPsecSiteConnectionTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_ipsec_site_connection(self):
        self.mockclient.create_ipsec_site_connection.return_value = {
            'ipsec_site_connection': {'id': 'con123'}
        }
        snippet = template_format.parse(ipsec_site_connection_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return vpnservice.IPsecSiteConnection(
            'ipsec_site_connection',
            resource_defns['IPsecSiteConnection'],
            self.stack)

    def test_create(self):
        rsrc = self.create_ipsec_site_connection()
        self.mockclient.show_ipsec_site_connection.return_value = {
            'ipsec_site_connection': {'status': 'ACTIVE'}
        }

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.show_ipsec_site_connection.assert_called_once_with(
            'con123')

    def test_create_failed(self):
        self.mockclient.create_ipsec_site_connection.side_effect = (
            exceptions.NeutronClientException)

        snippet = template_format.parse(ipsec_site_connection_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = vpnservice.IPsecSiteConnection(
            'ipsec_site_connection',
            resource_defns['IPsecSiteConnection'],
            self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.ipsec_site_connection: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)

    def test_create_failed_error_status(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        rsrc = self.create_ipsec_site_connection()
        self.mockclient.show_ipsec_site_connection.side_effect = [
            {'ipsec_site_connection': {'status': 'PENDING_CREATE'}},
            {'ipsec_site_connection': {'status': 'ERROR'}},
        ]

        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'ResourceInError: resources.ipsec_site_connection: '
            'Went to status ERROR due to "Error in IPsecSiteConnection"',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.show_ipsec_site_connection.assert_called_with('con123')

    def test_delete(self):
        rsrc = self.create_ipsec_site_connection()
        self.mockclient.show_ipsec_site_connection.side_effect = [
            {'ipsec_site_connection': {'status': 'ACTIVE'}},
            exceptions.NeutronClientException(status_code=404),
        ]
        self.mockclient.delete_ipsec_site_connection.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.delete_ipsec_site_connection.assert_called_once_with(
            'con123')
        self.mockclient.show_ipsec_site_connection.assert_called_with('con123')
        self.assertEqual(2,
                         self.mockclient.show_ipsec_site_connection.call_count)

    def test_delete_already_gone(self):
        self.mockclient.show_ipsec_site_connection.return_value = {
            'ipsec_site_connection': {'status': 'ACTIVE'}
        }
        self.mockclient.delete_ipsec_site_connection.side_effect = (
            exceptions.NeutronClientException(status_code=404))
        rsrc = self.create_ipsec_site_connection()

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.show_ipsec_site_connection.assert_called_once_with(
            'con123')
        self.mockclient.delete_ipsec_site_connection.assert_called_once_with(
            'con123')

    def test_delete_failed(self):
        self.mockclient.show_ipsec_site_connection.return_value = {
            'ipsec_site_connection': {'status': 'ACTIVE'}
        }
        self.mockclient.delete_ipsec_site_connection.side_effect = (
            exceptions.NeutronClientException(status_code=400))
        rsrc = self.create_ipsec_site_connection()

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.ipsec_site_connection: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.show_ipsec_site_connection.assert_called_once_with(
            'con123')
        self.mockclient.delete_ipsec_site_connection.assert_called_once_with(
            'con123')

    def test_attribute(self):
        rsrc = self.create_ipsec_site_connection()
        self.mockclient.show_ipsec_site_connection.return_value = {
            'ipsec_site_connection': {'status': 'ACTIVE'}
        }

        scheduler.TaskRunner(rsrc.create)()
        self.mockclient.show_ipsec_site_connection.return_value = (
            self.IPSEC_SITE_CONNECTION_CONF)

        self.assertEqual('IPsecSiteConnection', rsrc.FnGetAtt('name'))
        self.assertEqual('My new VPN connection', rsrc.FnGetAtt('description'))
        self.assertEqual('172.24.4.233', rsrc.FnGetAtt('peer_address'))
        self.assertEqual('172.24.4.233', rsrc.FnGetAtt('peer_id'))
        self.assertEqual(['10.2.0.0/24'], rsrc.FnGetAtt('peer_cidrs'))
        self.assertEqual('hold', rsrc.FnGetAtt('dpd')['actions'])
        self.assertEqual(30, rsrc.FnGetAtt('dpd')['interval'])
        self.assertEqual(120, rsrc.FnGetAtt('dpd')['timeout'])
        self.assertEqual('secret', rsrc.FnGetAtt('psk'))
        self.assertEqual('bi-directional', rsrc.FnGetAtt('initiator'))
        self.assertIs(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual('ike123', rsrc.FnGetAtt('ikepolicy_id'))
        self.assertEqual('ips123', rsrc.FnGetAtt('ipsecpolicy_id'))
        self.assertEqual('vpn123', rsrc.FnGetAtt('vpnservice_id'))

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.show_ipsec_site_connection.assert_called_with('con123')

    def test_attribute_failed(self):
        rsrc = self.create_ipsec_site_connection()
        self.mockclient.show_ipsec_site_connection.return_value = {
            'ipsec_site_connection': {'status': 'ACTIVE'}
        }

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'non-existent_property')
        self.assertEqual(
            'The Referenced Attribute (ipsec_site_connection '
            'non-existent_property) is incorrect.',
            six.text_type(error))

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.show_ipsec_site_connection.assert_called_with('con123')

    def test_update(self):
        rsrc = self.create_ipsec_site_connection()
        self.mockclient.show_ipsec_site_connection.return_value = {
            'ipsec_site_connection': {'status': 'ACTIVE'}
        }
        self.mockclient.update_ipsec_site_connection.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        props = dict(rsrc.properties)
        props['admin_state_up'] = False
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.mockclient.create_ipsec_site_connection.assert_called_once_with(
            self.IPSEC_SITE_CONNECTION_CONF)
        self.mockclient.show_ipsec_site_connection.assert_called_with('con123')
        update = self.mockclient.update_ipsec_site_connection
        update.assert_called_once_with('con123', {
            'ipsec_site_connection': {'admin_state_up': False}
        })


class IKEPolicyTest(common.HeatTestCase):

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
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_ikepolicy(self):
        self.mockclient.create_ikepolicy.return_value = {
            'ikepolicy': {'id': 'ike123'}
        }
        snippet = template_format.parse(ikepolicy_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return vpnservice.IKEPolicy('ikepolicy',
                                    resource_defns['IKEPolicy'],
                                    self.stack)

    def test_create(self):
        rsrc = self.create_ikepolicy()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)

    def test_create_failed(self):
        self.mockclient.create_ikepolicy.side_effect = (
            exceptions.NeutronClientException)

        snippet = template_format.parse(ikepolicy_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = vpnservice.IKEPolicy(
            'ikepolicy',
            resource_defns['IKEPolicy'],
            self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.ikepolicy: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)

    def test_delete(self):
        rsrc = self.create_ikepolicy()
        self.mockclient.delete_ikepolicy.return_value = None
        self.mockclient.show_ikepolicy.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)
        self.mockclient.delete_ikepolicy.assert_called_once_with('ike123')
        self.mockclient.show_ikepolicy.assert_called_once_with('ike123')

    def test_delete_already_gone(self):
        rsrc = self.create_ikepolicy()
        self.mockclient.delete_ikepolicy.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)
        self.mockclient.delete_ikepolicy.assert_called_once_with('ike123')
        self.mockclient.show_ikepolicy.assert_not_called()

    def test_delete_failed(self):
        rsrc = self.create_ikepolicy()
        self.mockclient.delete_ikepolicy.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.ikepolicy: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)
        self.mockclient.delete_ikepolicy.assert_called_once_with('ike123')
        self.mockclient.show_ikepolicy.assert_not_called()

    def test_attribute(self):
        rsrc = self.create_ikepolicy()
        self.mockclient.show_ikepolicy.return_value = self.IKE_POLICY_CONF

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

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)
        self.mockclient.show_ikepolicy.assert_called_with('ike123')

    def test_attribute_failed(self):
        rsrc = self.create_ikepolicy()

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'non-existent_property')
        self.assertEqual(
            'The Referenced Attribute (ikepolicy non-existent_property) is '
            'incorrect.',
            six.text_type(error))

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)
        self.mockclient.show_ikepolicy.assert_not_called()

    def test_update(self):
        rsrc = self.create_ikepolicy()
        self.mockclient.update_ikepolicy.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        props = dict(rsrc.properties)
        props['name'] = 'New IKEPolicy'
        props['auth_algorithm'] = 'sha512'
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.mockclient.create_ikepolicy.assert_called_once_with(
            self.IKE_POLICY_CONF)
        update_body = {
            'ikepolicy': {
                'name': 'New IKEPolicy',
                'auth_algorithm': 'sha512'
            }
        }
        self.mockclient.update_ikepolicy.assert_called_once_with(
            'ike123', update_body)


class IPsecPolicyTest(common.HeatTestCase):

    IPSEC_POLICY_CONF = {
        'ipsecpolicy': {
            'name': 'IPsecPolicy',
            'description': 'My new IPsec policy',
            'transform_protocol': 'esp',
            'encapsulation_mode': 'tunnel',
            'auth_algorithm': 'sha1',
            'encryption_algorithm': '3des',
            'lifetime': {
                'units': 'seconds',
                'value': 3600
            },
            'pfs': 'group5'
        }
    }

    def setUp(self):
        super(IPsecPolicyTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)

    def create_ipsecpolicy(self):
        self.mockclient.create_ipsecpolicy.return_value = {
            'ipsecpolicy': {'id': 'ips123'}
        }
        snippet = template_format.parse(ipsecpolicy_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return vpnservice.IPsecPolicy('ipsecpolicy',
                                      resource_defns['IPsecPolicy'],
                                      self.stack)

    def test_create(self):
        rsrc = self.create_ipsecpolicy()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)

    def test_create_failed(self):
        self.mockclient.create_ipsecpolicy.side_effect = (
            exceptions.NeutronClientException)

        snippet = template_format.parse(ipsecpolicy_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = vpnservice.IPsecPolicy(
            'ipsecpolicy',
            resource_defns['IPsecPolicy'],
            self.stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.ipsecpolicy: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)

    def test_delete(self):
        rsrc = self.create_ipsecpolicy()
        self.mockclient.delete_ipsecpolicy.return_value = None
        self.mockclient.show_ipsecpolicy.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)
        self.mockclient.delete_ipsecpolicy.assert_called_once_with('ips123')
        self.mockclient.show_ipsecpolicy.assert_called_once_with('ips123')

    def test_delete_already_gone(self):
        rsrc = self.create_ipsecpolicy()
        self.mockclient.delete_ipsecpolicy.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)
        self.mockclient.delete_ipsecpolicy.assert_called_once_with('ips123')
        self.mockclient.show_ipsecpolicy.assert_not_called()

    def test_delete_failed(self):
        rsrc = self.create_ipsecpolicy()
        self.mockclient.delete_ipsecpolicy.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.ipsecpolicy: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)
        self.mockclient.delete_ipsecpolicy.assert_called_once_with('ips123')
        self.mockclient.show_ipsecpolicy.assert_not_called()

    def test_attribute(self):
        rsrc = self.create_ipsecpolicy()
        self.mockclient.show_ipsecpolicy.return_value = self.IPSEC_POLICY_CONF

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('IPsecPolicy', rsrc.FnGetAtt('name'))
        self.assertEqual('My new IPsec policy', rsrc.FnGetAtt('description'))
        self.assertEqual('esp', rsrc.FnGetAtt('transform_protocol'))
        self.assertEqual('tunnel', rsrc.FnGetAtt('encapsulation_mode'))
        self.assertEqual('sha1', rsrc.FnGetAtt('auth_algorithm'))
        self.assertEqual('3des', rsrc.FnGetAtt('encryption_algorithm'))
        self.assertEqual('seconds', rsrc.FnGetAtt('lifetime')['units'])
        self.assertEqual(3600, rsrc.FnGetAtt('lifetime')['value'])
        self.assertEqual('group5', rsrc.FnGetAtt('pfs'))

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)
        self.mockclient.show_ipsecpolicy.assert_called_with('ips123')

    def test_attribute_failed(self):
        rsrc = self.create_ipsecpolicy()

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.InvalidTemplateAttribute,
                                  rsrc.FnGetAtt, 'non-existent_property')
        self.assertEqual(
            'The Referenced Attribute (ipsecpolicy non-existent_property) is '
            'incorrect.',
            six.text_type(error))

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)
        self.mockclient.show_ipsecpolicy.assert_not_called()

    def test_update(self):
        rsrc = self.create_ipsecpolicy()
        self.mockclient.update_ipsecpolicy.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        update_template = copy.deepcopy(rsrc.t)
        props = dict(rsrc.properties)
        props['name'] = 'New IPsecPolicy'
        update_template = rsrc.t.freeze(properties=props)
        scheduler.TaskRunner(rsrc.update, update_template)()

        self.mockclient.create_ipsecpolicy.assert_called_once_with(
            self.IPSEC_POLICY_CONF)
        self.mockclient.update_ipsecpolicy.assert_called_once_with(
            'ips123',
            {'ipsecpolicy': {'name': 'New IPsecPolicy'}})
        self.mockclient.show_ipsecpolicy.assert_not_called()
