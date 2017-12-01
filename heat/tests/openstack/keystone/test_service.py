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
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.keystone import service
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

keystone_service_template = {
    'heat_template_version': '2015-04-30',
    'resources': {
        'test_service': {
            'type': 'OS::Keystone::Service',
            'properties': {
                'name': 'test_service_1',
                'description': 'Test service',
                'type': 'orchestration',
                'enabled': False
            }
        }
    }
}


class KeystoneServiceTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneServiceTest, self).setUp()

        self.ctx = utils.dummy_context()

        # Mock client
        self.keystoneclient = mock.Mock()
        self.patchobject(resource.Resource, 'client',
                         return_value=fake_ks.FakeKeystoneClient(
                             client=self.keystoneclient))
        self.services = self.keystoneclient.services

        # Mock client plugin
        self.keystone_client_plugin = mock.MagicMock()

    def _setup_service_resource(self, stack_name, use_default=False):
        tmpl_data = copy.deepcopy(keystone_service_template)
        if use_default:
            props = tmpl_data['resources']['test_service']['properties']
            del props['name']
            del props['enabled']
            del props['description']

        test_stack = stack.Stack(
            self.ctx, stack_name,
            template.Template(tmpl_data)
        )
        r_service = test_stack['test_service']
        r_service.client = mock.MagicMock()
        r_service.client.return_value = self.keystoneclient
        r_service.client_plugin = mock.MagicMock()
        r_service.client_plugin.return_value = self.keystone_client_plugin

        return r_service

    def _get_mock_service(self):
        value = mock.MagicMock()
        value.id = '477e8273-60a7-4c41-b683-fdb0bc7cd152'

        return value

    def test_service_handle_create(self):
        rsrc = self._setup_service_resource('test_service_create')
        mock_service = self._get_mock_service()
        self.services.create.return_value = mock_service

        # validate the properties
        self.assertEqual(
            'test_service_1',
            rsrc.properties.get(service.KeystoneService.NAME))
        self.assertEqual(
            'Test service',
            rsrc.properties.get(
                service.KeystoneService.DESCRIPTION))
        self.assertEqual(
            'orchestration',
            rsrc.properties.get(service.KeystoneService.TYPE))
        self.assertFalse(rsrc.properties.get(
            service.KeystoneService.ENABLED))

        rsrc.handle_create()

        # validate service creation
        self.services.create.assert_called_once_with(
            name='test_service_1',
            description='Test service',
            type='orchestration',
            enabled=False)

        # validate physical resource id
        self.assertEqual(mock_service.id, rsrc.resource_id)

    def test_service_handle_create_default(self):
        rsrc = self._setup_service_resource('test_create_with_defaults',
                                            use_default=True)
        mock_service = self._get_mock_service()
        self.services.create.return_value = mock_service

        rsrc.physical_resource_name = mock.MagicMock()
        rsrc.physical_resource_name.return_value = 'foo'

        # validate the properties
        self.assertIsNone(
            rsrc.properties.get(service.KeystoneService.NAME))
        self.assertIsNone(rsrc.properties.get(
            service.KeystoneService.DESCRIPTION))
        self.assertEqual(
            'orchestration',
            rsrc.properties.get(service.KeystoneService.TYPE))
        self.assertTrue(rsrc.properties.get(service.KeystoneService.ENABLED))

        rsrc.handle_create()

        # validate service creation with physical resource name
        self.services.create.assert_called_once_with(
            name='foo',
            description=None,
            type='orchestration',
            enabled=True)

    def test_service_handle_update(self):
        rsrc = self._setup_service_resource('test_update')
        rsrc.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {service.KeystoneService.NAME: 'test_service_1_updated',
                     service.KeystoneService.DESCRIPTION:
                         'Test Service updated',
                     service.KeystoneService.TYPE: 'heat_updated',
                     service.KeystoneService.ENABLED: False}

        rsrc.handle_update(json_snippet=None,
                           tmpl_diff=None,
                           prop_diff=prop_diff)

        self.services.update.assert_called_once_with(
            service=rsrc.resource_id,
            name=prop_diff[service.KeystoneService.NAME],
            description=prop_diff[service.KeystoneService.DESCRIPTION],
            type=prop_diff[service.KeystoneService.TYPE],
            enabled=prop_diff[service.KeystoneService.ENABLED]
        )

    def test_service_handle_update_default_name(self):
        rsrc = self._setup_service_resource('test_update_default_name')
        rsrc.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        rsrc.physical_resource_name = mock.MagicMock()
        rsrc.physical_resource_name.return_value = 'foo'

        # Name is reset to None, so default to physical resource name
        prop_diff = {service.KeystoneService.NAME: None}

        rsrc.handle_update(json_snippet=None,
                           tmpl_diff=None,
                           prop_diff=prop_diff)

        # validate default name to physical resource name
        self.services.update.assert_called_once_with(
            service=rsrc.resource_id,
            name='foo',
            type=None,
            description=None,
            enabled=None
        )

    def test_service_handle_update_only_enabled(self):
        rsrc = self._setup_service_resource('test_update_enabled_only')
        rsrc.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {service.KeystoneService.ENABLED: False}

        rsrc.handle_update(json_snippet=None,
                           tmpl_diff=None,
                           prop_diff=prop_diff)

        self.services.update.assert_called_once_with(
            service=rsrc.resource_id,
            name=None,
            description=None,
            type=None,
            enabled=prop_diff[service.KeystoneService.ENABLED]
        )

    def test_properties_title(self):
        property_title_map = {
            service.KeystoneService.NAME: 'name',
            service.KeystoneService.DESCRIPTION: 'description',
            service.KeystoneService.TYPE: 'type',
            service.KeystoneService.ENABLED: 'enabled'
        }

        for actual_title, expected_title in property_title_map.items():
            self.assertEqual(
                expected_title,
                actual_title,
                'KeystoneService PROPERTIES(%s) title modified.' %
                actual_title)

    def test_property_name_validate_schema(self):
        schema = service.KeystoneService.properties_schema[
            service.KeystoneService.NAME]
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            service.KeystoneService.NAME)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         service.KeystoneService.NAME)

        self.assertEqual('Name of keystone service.',
                         schema.description,
                         'description for property %s is modified' %
                         service.KeystoneService.NAME)

    def test_property_description_validate_schema(self):
        schema = service.KeystoneService.properties_schema[
            service.KeystoneService.DESCRIPTION]
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            service.KeystoneService.DESCRIPTION)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         service.KeystoneService.DESCRIPTION)

        self.assertEqual('Description of keystone service.',
                         schema.description,
                         'description for property %s is modified' %
                         service.KeystoneService.DESCRIPTION)

    def test_property_type_validate_schema(self):
        schema = service.KeystoneService.properties_schema[
            service.KeystoneService.TYPE]
        self.assertTrue(
            schema.update_allowed,
            'update_allowed for property %s is modified' %
            service.KeystoneService.TYPE)

        self.assertTrue(
            schema.required,
            'required for property %s is modified' %
            service.KeystoneService.TYPE)

        self.assertEqual(properties.Schema.STRING,
                         schema.type,
                         'type for property %s is modified' %
                         service.KeystoneService.TYPE)

        self.assertEqual('Type of keystone Service.',
                         schema.description,
                         'description for property %s is modified' %
                         service.KeystoneService.TYPE)

    def test_show_resource(self):
        rsrc = self._setup_service_resource('test_show_resource')
        moc_service = mock.Mock()
        moc_service.to_dict.return_value = {'attr': 'val'}
        self.services.get.return_value = moc_service
        attributes = rsrc._show_resource()
        self.assertEqual({'attr': 'val'}, attributes)
