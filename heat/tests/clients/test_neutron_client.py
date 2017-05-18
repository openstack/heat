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
        self.neutron_plugin.client = lambda: self.neutron_client


class NeutronClientPluginTest(NeutronClientPluginTestCase):
    def setUp(self):
        super(NeutronClientPluginTest, self).setUp()
        self.mock_find = self.patchobject(neutron.neutronV20,
                                          'find_resourceid_by_name_or_id')
        self.mock_find.return_value = 42

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

    def test_check_lb_status(self):
        self.neutron_client.show_loadbalancer.side_effect = [
            {'loadbalancer': {'provisioning_status': 'ACTIVE'}},
            {'loadbalancer': {'provisioning_status': 'PENDING_CREATE'}},
            {'loadbalancer': {'provisioning_status': 'ERROR'}}
        ]

        self.assertTrue(self.neutron_plugin.check_lb_status('1234'))
        self.assertFalse(self.neutron_plugin.check_lb_status('1234'))
        self.assertRaises(exception.ResourceInError,
                          self.neutron_plugin.check_lb_status,
                          '1234')


class NeutronConstraintsValidate(common.HeatTestCase):
    scenarios = [
        ('validate_network',
            dict(constraint_class=nc.NetworkConstraint,
                 resource_type='network')),
        ('validate_port',
            dict(constraint_class=nc.PortConstraint,
                 resource_type='port')),
        ('validate_router',
            dict(constraint_class=nc.RouterConstraint,
                 resource_type='router')),
        ('validate_subnet',
            dict(constraint_class=nc.SubnetConstraint,
                 resource_type='subnet')),
        ('validate_subnetpool',
            dict(constraint_class=nc.SubnetPoolConstraint,
                 resource_type='subnetpool')),
        ('validate_address_scope',
            dict(constraint_class=nc.AddressScopeConstraint,
                 resource_type='address_scope')),
        ('validate_loadbalancer',
            dict(constraint_class=lc.LoadbalancerConstraint,
                 resource_type='loadbalancer')),
        ('validate_listener',
            dict(constraint_class=lc.ListenerConstraint,
                 resource_type='listener')),
        ('validate_pool',
            dict(constraint_class=lc.PoolConstraint,
                 resource_type='pool')),
        ('validate_qos_policy',
            dict(constraint_class=nc.QoSPolicyConstraint,
                 resource_type='policy')),
        ('validate_security_group',
            dict(constraint_class=nc.SecurityGroupConstraint,
                 resource_type='security_group'))
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
            [mock.call(self.resource_type, 'foo'),
             mock.call(self.resource_type, 'bar')])


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


class NeutronClientPluginExtensionsTest(NeutronClientPluginTestCase):
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
