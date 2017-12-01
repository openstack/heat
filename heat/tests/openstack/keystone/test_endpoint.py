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

from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.keystone import endpoint
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

keystone_endpoint_template = {
    'heat_template_version': '2015-04-30',
    'resources': {
        'test_endpoint': {
            'type': 'OS::Keystone::Endpoint',
            'properties': {
                'service': 'heat',
                'region': 'RegionOne',
                'interface': 'public',
                'url': 'http://127.0.0.1:8004/v1/tenant-id',
                'name': 'endpoint_foo',
                'enabled': False
            }
        }
    }
}


class KeystoneEndpointTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneEndpointTest, self).setUp()

        self.ctx = utils.dummy_context()

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.endpoints = self.keystoneclient.endpoints

        # Mock client plugin
        self.keystone_client_plugin = mock.MagicMock()

    def _get_mock_endpoint(self):
        value = mock.MagicMock()
        value.id = '477e8273-60a7-4c41-b683-fdb0bc7cd152'

        return value

    def _setup_endpoint_resource(self, stack_name, use_default=False):
        tmpl_data = copy.deepcopy(keystone_endpoint_template)
        if use_default:
            props = tmpl_data['resources']['test_endpoint']['properties']
            del props['name']
            del props['enabled']

        test_stack = stack.Stack(
            self.ctx, stack_name,
            template.Template(tmpl_data)
        )

        r_endpoint = test_stack['test_endpoint']
        r_endpoint.client = mock.MagicMock()
        r_endpoint.client.return_value = self.keystoneclient
        r_endpoint.client_plugin = mock.MagicMock()
        r_endpoint.client_plugin.return_value = self.keystone_client_plugin

        return r_endpoint

    def test_endpoint_handle_create(self):
        rsrc = self._setup_endpoint_resource('test_endpoint_create')
        mock_endpoint = self._get_mock_endpoint()
        self.endpoints.create.return_value = mock_endpoint

        # validate the properties
        self.assertEqual(
            'heat', rsrc.properties.get(endpoint.KeystoneEndpoint.SERVICE))
        self.assertEqual(
            'public',
            rsrc.properties.get(endpoint.KeystoneEndpoint.INTERFACE))
        self.assertEqual(
            'RegionOne',
            rsrc.properties.get(endpoint.KeystoneEndpoint.REGION))
        self.assertEqual(
            'http://127.0.0.1:8004/v1/tenant-id',
            rsrc.properties.get(endpoint.KeystoneEndpoint.SERVICE_URL))
        self.assertEqual(
            'endpoint_foo',
            rsrc.properties.get(endpoint.KeystoneEndpoint.NAME))
        self.assertFalse(rsrc.properties.get(
            endpoint.KeystoneEndpoint.ENABLED))

        rsrc.handle_create()

        # validate endpoint creation
        self.endpoints.create.assert_called_once_with(
            service='heat',
            url='http://127.0.0.1:8004/v1/tenant-id',
            interface='public',
            region='RegionOne',
            name='endpoint_foo',
            enabled=False)

        # validate physical resource id
        self.assertEqual(mock_endpoint.id, rsrc.resource_id)

    def test_endpoint_handle_create_default(self):
        rsrc = self._setup_endpoint_resource('test_create_with_defaults',
                                             use_default=True)
        mock_endpoint = self._get_mock_endpoint()
        self.endpoints.create.return_value = mock_endpoint

        rsrc.physical_resource_name = mock.MagicMock()
        rsrc.physical_resource_name.return_value = 'stack_endpoint_foo'

        # validate the properties
        self.assertIsNone(
            rsrc.properties.get(endpoint.KeystoneEndpoint.NAME))
        self.assertTrue(rsrc.properties.get(
            endpoint.KeystoneEndpoint.ENABLED))

        rsrc.handle_create()

        # validate endpoints creation with physical resource name
        # and with enabled(default is True)
        self.endpoints.create.assert_called_once_with(
            service='heat',
            url='http://127.0.0.1:8004/v1/tenant-id',
            interface='public',
            region='RegionOne',
            name='stack_endpoint_foo',
            enabled=True)

    def test_endpoint_handle_update(self):
        rsrc = self._setup_endpoint_resource('test_endpoint_update')
        rsrc.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {endpoint.KeystoneEndpoint.REGION: 'RegionTwo',
                     endpoint.KeystoneEndpoint.INTERFACE: 'internal',
                     endpoint.KeystoneEndpoint.SERVICE: 'updated_id',
                     endpoint.KeystoneEndpoint.SERVICE_URL:
                         'http://127.0.0.1:8004/v2/tenant-id',
                     endpoint.KeystoneEndpoint.NAME:
                         'endpoint_foo_updated',
                     endpoint.KeystoneEndpoint.ENABLED: True}

        rsrc.handle_update(json_snippet=None,
                           tmpl_diff=None,
                           prop_diff=prop_diff)

        self.endpoints.update.assert_called_once_with(
            endpoint=rsrc.resource_id,
            region=prop_diff[endpoint.KeystoneEndpoint.REGION],
            interface=prop_diff[endpoint.KeystoneEndpoint.INTERFACE],
            service=prop_diff[endpoint.KeystoneEndpoint.SERVICE],
            url=prop_diff[endpoint.KeystoneEndpoint.SERVICE_URL],
            name=prop_diff[endpoint.KeystoneEndpoint.NAME],
            enabled=prop_diff[endpoint.KeystoneEndpoint.ENABLED]
        )

    def test_endpoint_handle_update_default(self):
        rsrc = self._setup_endpoint_resource('test_endpoint_update_default')
        rsrc.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        rsrc.physical_resource_name = mock.MagicMock()
        rsrc.physical_resource_name.return_value = 'stack_endpoint_foo'

        # Name is reset to None, so default to physical resource name
        prop_diff = {endpoint.KeystoneEndpoint.NAME: None}

        rsrc.handle_update(json_snippet=None,
                           tmpl_diff=None,
                           prop_diff=prop_diff)

        # validate default name to physical resource name
        self.endpoints.update.assert_called_once_with(
            endpoint=rsrc.resource_id,
            region=None,
            interface=None,
            service=None,
            url=None,
            name='stack_endpoint_foo',
            enabled=None
        )

    def test_endpoint_handle_update_only_enabled(self):
        rsrc = self._setup_endpoint_resource('test_endpoint_update_enabled')
        rsrc.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {endpoint.KeystoneEndpoint.ENABLED: True}

        rsrc.handle_update(json_snippet=None,
                           tmpl_diff=None,
                           prop_diff=prop_diff)

        self.endpoints.update.assert_called_once_with(
            endpoint=rsrc.resource_id,
            region=None,
            interface=None,
            service=None,
            url=None,
            name=None,
            enabled=prop_diff[endpoint.KeystoneEndpoint.ENABLED]
        )

    def test_properties_title(self):
        property_title_map = {
            endpoint.KeystoneEndpoint.SERVICE: 'service',
            endpoint.KeystoneEndpoint.REGION: 'region',
            endpoint.KeystoneEndpoint.INTERFACE: 'interface',
            endpoint.KeystoneEndpoint.SERVICE_URL: 'url',
            endpoint.KeystoneEndpoint.NAME: 'name',
            endpoint.KeystoneEndpoint.ENABLED: 'enabled'
        }

        for actual_title, expected_title in property_title_map.items():
            self.assertEqual(
                expected_title,
                actual_title,
                'KeystoneEndpoint PROPERTIES(%s) title modified.' %
                actual_title)

    def test_property_service_validate_schema(self):
        schema = (endpoint.KeystoneEndpoint.properties_schema[
                  endpoint.KeystoneEndpoint.SERVICE])
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            endpoint.KeystoneEndpoint.SERVICE)

        self.assertTrue(
            schema.required,
            'required for property %s is modified' %
            endpoint.KeystoneEndpoint.SERVICE)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         endpoint.KeystoneEndpoint.SERVICE)

        self.assertEqual('Name or Id of keystone service.',
                         schema.description,
                         'description for property %s is modified' %
                         endpoint.KeystoneEndpoint.SERVICE)

        # Make sure, SERVICE is of keystone.service custom constrain type
        self.assertEqual(1, len(schema.constraints))
        keystone_service_constrain = schema.constraints[0]
        self.assertIsInstance(keystone_service_constrain,
                              constraints.CustomConstraint)
        self.assertEqual('keystone.service',
                         keystone_service_constrain.name)

    def test_property_region_validate_schema(self):
        schema = (endpoint.KeystoneEndpoint.properties_schema[
                  endpoint.KeystoneEndpoint.REGION])
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            endpoint.KeystoneEndpoint.REGION)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         endpoint.KeystoneEndpoint.REGION)

        self.assertEqual('Name or Id of keystone region.',
                         schema.description,
                         'description for property %s is modified' %
                         endpoint.KeystoneEndpoint.REGION)

        # Make sure, REGION is of keystone.region custom constraint type
        self.assertEqual(1, len(schema.constraints))
        keystone_region_constraint = schema.constraints[0]
        self.assertIsInstance(keystone_region_constraint,
                              constraints.CustomConstraint)
        self.assertEqual('keystone.region',
                         keystone_region_constraint.name)

    def test_property_interface_validate_schema(self):
        schema = (endpoint.KeystoneEndpoint.properties_schema[
                  endpoint.KeystoneEndpoint.INTERFACE])
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            endpoint.KeystoneEndpoint.INTERFACE)

        self.assertTrue(
            schema.required,
            'required for property %s is modified' %
            endpoint.KeystoneEndpoint.INTERFACE)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         endpoint.KeystoneEndpoint.INTERFACE)

        self.assertEqual('Interface type of keystone service endpoint.',
                         schema.description,
                         'description for property %s is modified' %
                         endpoint.KeystoneEndpoint.INTERFACE)

        # Make sure INTERFACE valid constrains
        self.assertEqual(1, len(schema.constraints))
        allowed_constrain = schema.constraints[0]
        self.assertIsInstance(allowed_constrain,
                              constraints.AllowedValues)
        self.assertEqual(('public', 'internal', 'admin'),
                         allowed_constrain.allowed)

    def test_property_service_url_validate_schema(self):
        schema = (endpoint.KeystoneEndpoint.properties_schema[
                  endpoint.KeystoneEndpoint.SERVICE_URL])
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            endpoint.KeystoneEndpoint.SERVICE_URL)

        self.assertTrue(
            schema.required,
            'required for property %s is modified' %
            endpoint.KeystoneEndpoint.SERVICE_URL)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         endpoint.KeystoneEndpoint.SERVICE_URL)

        self.assertEqual('URL of keystone service endpoint.',
                         schema.description,
                         'description for property %s is modified' %
                         endpoint.KeystoneEndpoint.SERVICE_URL)

    def test_property_name_validate_schema(self):
        schema = (endpoint.KeystoneEndpoint.properties_schema[
                  endpoint.KeystoneEndpoint.NAME])
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            endpoint.KeystoneEndpoint.NAME)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         endpoint.KeystoneEndpoint.NAME)

        self.assertEqual('Name of keystone endpoint.',
                         schema.description,
                         'description for property %s is modified' %
                         endpoint.KeystoneEndpoint.NAME)

    def test_show_resource(self):
        rsrc = self._setup_endpoint_resource('test_show_resource')
        mock_endpoint = mock.Mock()
        mock_endpoint.to_dict.return_value = {'attr': 'val'}
        self.endpoints.get.return_value = mock_endpoint
        attrs = rsrc._show_resource()
        self.assertEqual({'attr': 'val'}, attrs)

    def test_get_live_state(self):
        rsrc = self._setup_endpoint_resource('test_get_live_state')
        mock_endpoint = mock.Mock()
        mock_endpoint.to_dict.return_value = {
            'region_id': 'RegionOne',
            'links': {'self': 'some_link'},
            'url': 'http://127.0.0.1:8004/v1/1234',
            'region': 'RegionOne',
            'enabled': True,
            'interface': 'admin',
            'service_id': '934f10ea63c24d82a8d9370cc0a1cb3b',
            'id': '7f1944ae8c524e2799119b5f2dcf9781',
            'name': 'fake'}
        self.endpoints.get.return_value = mock_endpoint

        reality = rsrc.get_live_state(rsrc.properties)
        expected = {
            'region': 'RegionOne',
            'enabled': True,
            'interface': 'admin',
            'service': '934f10ea63c24d82a8d9370cc0a1cb3b',
            'name': 'fake',
            'url': 'http://127.0.0.1:8004/v1/1234'
        }

        self.assertEqual(expected, reality)
