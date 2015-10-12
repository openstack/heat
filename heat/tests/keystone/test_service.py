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

import mock

from heat.engine import properties
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
                'type': 'orchestration'
            }
        }
    }
}

RESOURCE_TYPE = 'OS::Keystone::Service'


class KeystoneServiceTest(common.HeatTestCase):
    def setUp(self):
        super(KeystoneServiceTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack_keystone',
            template.Template(keystone_service_template)
        )

        self.test_service = self.stack['test_service']

        # Mock client
        self.keystoneclient = mock.MagicMock()
        self.test_service.client = mock.MagicMock()
        self.test_service.client.return_value = self.keystoneclient
        self.services = self.keystoneclient.services

        # Mock client plugin
        keystone_client_plugin = mock.MagicMock()
        self.test_service.client_plugin = mock.MagicMock()
        self.test_service.client_plugin.return_value = keystone_client_plugin

    def _get_mock_service(self):
        value = mock.MagicMock()
        value.id = '477e8273-60a7-4c41-b683-fdb0bc7cd152'

        return value

    def test_service_handle_create(self):
        mock_service = self._get_mock_service()
        self.services.create.return_value = mock_service

        # validate the properties
        self.assertEqual(
            'test_service_1',
            self.test_service.properties.get(service.KeystoneService.NAME))
        self.assertEqual(
            'Test service',
            self.test_service.properties.get(
                service.KeystoneService.DESCRIPTION))
        self.assertEqual(
            'orchestration',
            self.test_service.properties.get(service.KeystoneService.TYPE))

        self.test_service.handle_create()

        # validate service creation
        self.services.create.assert_called_once_with(
            name='test_service_1',
            description='Test service',
            type='orchestration')

        # validate physical resource id
        self.assertEqual(mock_service.id, self.test_service.resource_id)

    def test_service_handle_create_default(self):
        values = {
            service.KeystoneService.NAME: None,
            service.KeystoneService.DESCRIPTION: None,
            service.KeystoneService.TYPE: 'orchestration'
        }

        def _side_effect(key):
            return values[key]

        mock_service = self._get_mock_service()
        self.services.create.return_value = mock_service
        self.test_service.properties = mock.MagicMock()
        self.test_service.properties.get.side_effect = _side_effect
        self.test_service.properties.__getitem__.side_effect = _side_effect

        self.test_service.physical_resource_name = mock.MagicMock()
        self.test_service.physical_resource_name.return_value = 'foo'

        # validate the properties
        self.assertIsNone(
            self.test_service.properties.get(service.KeystoneService.NAME))
        self.assertIsNone(
            self.test_service.properties.get(
                service.KeystoneService.DESCRIPTION))
        self.assertEqual(
            'orchestration',
            self.test_service.properties.get(service.KeystoneService.TYPE))

        self.test_service.handle_create()

        # validate service creation with physical resource name
        self.services.create.assert_called_once_with(
            name='foo',
            description=None,
            type='orchestration')

    def test_service_handle_update(self):
        self.test_service.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {service.KeystoneService.NAME: 'test_service_1_updated',
                     service.KeystoneService.DESCRIPTION:
                         'Test Service updated',
                     service.KeystoneService.TYPE: 'heat_updated'}

        self.test_service.handle_update(json_snippet=None,
                                        tmpl_diff=None,
                                        prop_diff=prop_diff)

        self.services.update.assert_called_once_with(
            service=self.test_service.resource_id,
            name=prop_diff[service.KeystoneService.NAME],
            description=prop_diff[service.KeystoneService.DESCRIPTION],
            type=prop_diff[service.KeystoneService.TYPE]
        )

    def test_service_handle_update_default(self):
        self.test_service.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.test_service.physical_resource_name = mock.MagicMock()
        self.test_service.physical_resource_name.return_value = 'foo'

        # Name is reset to None, so default to physical resource name
        prop_diff = {service.KeystoneService.NAME: None}

        self.test_service.handle_update(json_snippet=None,
                                        tmpl_diff=None,
                                        prop_diff=prop_diff)

        # validate default name to physical resource name
        self.services.update.assert_called_once_with(
            service=self.test_service.resource_id,
            name='foo',
            type=None,
            description=None
        )

    def test_resource_mapping(self):
        mapping = service.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(service.KeystoneService, mapping[RESOURCE_TYPE])
        self.assertIsInstance(self.test_service, service.KeystoneService)

    def test_properties_title(self):
        property_title_map = {
            service.KeystoneService.NAME: 'name',
            service.KeystoneService.DESCRIPTION: 'description',
            service.KeystoneService.TYPE: 'type'
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
        service = mock.Mock()
        service.to_dict.return_value = {'attr': 'val'}
        self.services.get.return_value = service
        res = self.test_service._show_resource()
        self.assertEqual({'attr': 'val'}, res)
