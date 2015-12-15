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

import six

import mock
from neutronclient.common import exceptions as qe

from heat.common import exception
from heat.engine.clients.os import neutron
from heat.engine.clients.os.neutron import lbaas_constraints as lc
from heat.engine.clients.os.neutron import neutron_constraints as nc
from heat.tests import common
from heat.tests import utils


class NeutronClientPluginTestCase(common.HeatTestCase):
    def setUp(self):
        super(NeutronClientPluginTestCase, self).setUp()
        self.neutron_client = mock.MagicMock()

        con = utils.dummy_context()
        c = con.clients
        self.neutron_plugin = c.client_plugin('neutron')
        self.neutron_plugin._client = self.neutron_client


class NeutronClientPluginTests(NeutronClientPluginTestCase):
    def setUp(self):
        super(NeutronClientPluginTests, self).setUp()
        self.mock_find = self.patchobject(neutron.neutronV20,
                                          'find_resourceid_by_name_or_id')
        self.mock_find.return_value = 42

    def test_find_neutron_resource(self):
        props = {'net': 'test_network'}

        res = self.neutron_plugin.find_neutron_resource(props, 'net',
                                                        'network')
        self.assertEqual(42, res)
        self.mock_find.assert_called_once_with(self.neutron_client, 'network',
                                               'test_network',
                                               cmd_resource=None)

    def test_resolve_network(self):
        props = {'net': 'test_network'}

        res = self.neutron_plugin.resolve_network(props, 'net', 'net_id')
        self.assertEqual(42, res)
        self.mock_find.assert_called_once_with(self.neutron_client, 'network',
                                               'test_network',
                                               cmd_resource=None)

        # check resolve if was send id instead of name
        props = {'net_id': 77}
        res = self.neutron_plugin.resolve_network(props, 'net', 'net_id')
        self.assertEqual(77, res)
        # in this case find_resourceid_by_name_or_id is not called
        self.mock_find.assert_called_once_with(self.neutron_client, 'network',
                                               'test_network',
                                               cmd_resource=None)

    def test_resolve_subnet(self):
        props = {'snet': 'test_subnet'}

        res = self.neutron_plugin.resolve_subnet(props, 'snet', 'snet_id')
        self.assertEqual(42, res)
        self.mock_find.assert_called_once_with(self.neutron_client, 'subnet',
                                               'test_subnet',
                                               cmd_resource=None)

        # check resolve if was send id instead of name
        props = {'snet_id': 77}
        res = self.neutron_plugin.resolve_subnet(props, 'snet', 'snet_id')
        self.assertEqual(77, res)
        # in this case find_resourceid_by_name_or_id is not called
        self.mock_find.assert_called_once_with(self.neutron_client, 'subnet',
                                               'test_subnet',
                                               cmd_resource=None)

    def test_get_secgroup_uuids(self):
        # test get from uuids
        sgs_uuid = ['b62c3079-6946-44f5-a67b-6b9091884d4f',
                    '9887157c-d092-40f5-b547-6361915fce7d']

        sgs_list = self.neutron_plugin.get_secgroup_uuids(sgs_uuid)
        self.assertEqual(sgs_uuid, sgs_list)
        # test get from name, return only one
        sgs_non_uuid = ['security_group_1']
        expected_groups = ['0389f747-7785-4757-b7bb-2ab07e4b09c3']
        fake_list = {
            'security_groups': [
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.neutron_client.list_security_groups.return_value = fake_list
        self.assertEqual(expected_groups,
                         self.neutron_plugin.get_secgroup_uuids(sgs_non_uuid))
        # test only one belong to the tenant
        fake_list = {
            'security_groups': [
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'not_test_tenant_id',
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.neutron_client.list_security_groups.return_value = fake_list
        self.assertEqual(expected_groups,
                         self.neutron_plugin.get_secgroup_uuids(sgs_non_uuid))
        # test there are two securityGroups with same name, and the two
        # all belong to the tenant
        fake_list = {
            'security_groups': [
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '0389f747-7785-4757-b7bb-2ab07e4b09c3',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                },
                {
                    'tenant_id': 'test_tenant_id',
                    'id': '384ccd91-447c-4d83-832c-06974a7d3d05',
                    'name': 'security_group_1',
                    'security_group_rules': [],
                    'description': 'no protocol'
                }
            ]
        }
        self.neutron_client.list_security_groups.return_value = fake_list
        self.assertRaises(exception.PhysicalResourceNameAmbiguity,
                          self.neutron_plugin.get_secgroup_uuids,
                          sgs_non_uuid)


class NeutronConstraintsValidate(common.HeatTestCase):
    scenarios = [
        ('validate_network',
            dict(constraint_class=nc.NetworkConstraint,
                 resource_type='network',
                 cmd_resource=None)),
        ('validate_port',
            dict(constraint_class=nc.PortConstraint,
                 resource_type='port',
                 cmd_resource=None)),
        ('validate_router',
            dict(constraint_class=nc.RouterConstraint,
                 resource_type='router',
                 cmd_resource=None)),
        ('validate_subnet',
            dict(constraint_class=nc.SubnetConstraint,
                 resource_type='subnet',
                 cmd_resource=None)),
        ('validate_subnetpool',
            dict(constraint_class=nc.SubnetPoolConstraint,
                 resource_type='subnetpool',
                 cmd_resource=None)),
        ('validate_address_scope',
            dict(constraint_class=nc.AddressScopeConstraint,
                 resource_type='address_scope',
                 cmd_resource=None)),
        ('validate_loadbalancer',
            dict(constraint_class=lc.LoadbalancerConstraint,
                 resource_type='loadbalancer',
                 cmd_resource='lbaas_loadbalancer')),
        ('validate_listener',
            dict(constraint_class=lc.ListenerConstraint,
                 resource_type='listener',
                 cmd_resource=None)),
        ('validate_pool',
            dict(constraint_class=lc.PoolConstraint,
                 resource_type='pool',
                 cmd_resource='lbaas_pool')),
        ('validate_qos_policy',
            dict(constraint_class=nc.QoSPolicyConstraint,
                 resource_type='policy',
                 cmd_resource='qos_policy'))
    ]

    def test_validate(self):
        mock_extension = self.patchobject(
            neutron.NeutronClientPlugin, 'has_extension', return_value=True)
        nc = mock.Mock()
        mock_create = self.patchobject(neutron.NeutronClientPlugin, '_create')
        mock_create.return_value = nc
        mock_find = self.patchobject(neutron.NeutronClientPlugin,
                                     'find_resourceid_by_name_or_id')
        mock_find.side_effect = [
            'foo',
            qe.NeutronClientException(status_code=404)
        ]

        constraint = self.constraint_class()
        ctx = utils.dummy_context()
        if hasattr(constraint, 'extension') and constraint.extension:
            mock_extension.side_effect = [
                False,
                True,
                True,
            ]
            ex = self.assertRaises(
                exception.EntityNotFound,
                constraint.validate_with_client, ctx.clients, "foo"
            )
            expected = ("The neutron extension (%s) could not be found." %
                        constraint.extension)
            self.assertEqual(expected, six.text_type(ex))
        self.assertTrue(constraint.validate("foo", ctx))
        self.assertFalse(constraint.validate("bar", ctx))
        mock_find.assert_has_calls(
            [mock.call(self.resource_type, 'foo',
                       cmd_resource=self.cmd_resource),
             mock.call(self.resource_type, 'bar',
                       cmd_resource=self.cmd_resource)])


class NeutronProviderConstraintsValidate(common.HeatTestCase):
    scenarios = [
        ('validate_lbaasv1',
            dict(constraint_class=nc.LBaasV1ProviderConstraint,
                 service_type='LOADBALANCER')),
        ('validate_lbaasv2',
            dict(constraint_class=lc.LBaasV2ProviderConstraint,
                 service_type='LOADBALANCERV2'))
    ]

    def test_provider_validate(self):
        nc = mock.Mock()
        mock_create = self.patchobject(neutron.NeutronClientPlugin, '_create')
        mock_create.return_value = nc
        providers = {
            'service_providers': [
                {'service_type': 'LOADBANALCERV2', 'name': 'haproxy'},
                {'service_type': 'LOADBANALCER', 'name': 'haproxy'}
            ]
        }
        nc.list_service_providers.return_value = providers
        constraint = self.constraint_class()
        ctx = utils.dummy_context()
        self.assertTrue(constraint.validate('haproxy', ctx))
        self.assertFalse(constraint.validate("bar", ctx))


class NeutronClientPluginExtensionsTests(NeutronClientPluginTestCase):
    """Tests for extensions in neutronclient."""

    def test_has_no_extension(self):
        mock_extensions = {'extensions': []}
        self.neutron_client.list_extensions.return_value = mock_extensions
        self.assertFalse(self.neutron_plugin.has_extension('lbaas'))

    def test_without_service_extension(self):
        mock_extensions = {'extensions': [{'alias': 'router'}]}
        self.neutron_client.list_extensions.return_value = mock_extensions
        self.assertFalse(self.neutron_plugin.has_extension('lbaas'))

    def test_has_service_extension(self):
        mock_extensions = {'extensions': [{'alias': 'router'}]}
        self.neutron_client.list_extensions.return_value = mock_extensions
        self.assertTrue(self.neutron_plugin.has_extension('router'))
