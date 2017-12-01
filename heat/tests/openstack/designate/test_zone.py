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

from heat.common import exception
from heat.engine.resources.openstack.designate import zone
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


sample_template = {
    'heat_template_version': '2015-04-30',
    'resources': {
        'test_resource': {
            'type': 'OS::Designate::Zone',
            'properties': {
                'name': 'test-zone.com',
                'description': 'Test zone',
                'ttl': 3600,
                'email': 'abc@test-zone.com',
                'type': 'PRIMARY',
                'masters': []
            }
        }
    }
}


class DesignateZoneTest(common.HeatTestCase):

    def setUp(self):
        super(DesignateZoneTest, self).setUp()

        self.ctx = utils.dummy_context()

        self.stack = stack.Stack(
            self.ctx, 'test_stack',
            template.Template(sample_template)
        )

        self.test_resource = self.stack['test_resource']

        # Mock client plugin
        self.test_client_plugin = mock.MagicMock()
        self.test_resource.client_plugin = mock.MagicMock(
            return_value=self.test_client_plugin)

        # Mock client
        self.test_client = mock.MagicMock()
        self.test_resource.client = mock.MagicMock(
            return_value=self.test_client)

    def _get_mock_resource(self):
        value = {}
        value['id'] = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
        value['serial'] = '1434596972'

        return value

    def test_resource_handle_create(self):
        mock_zone_create = self.test_client.zones.create
        mock_resource = self._get_mock_resource()
        mock_zone_create.return_value = mock_resource

        # validate the properties
        self.assertEqual(
            'test-zone.com',
            self.test_resource.properties.get(zone.DesignateZone.NAME))
        self.assertEqual(
            'Test zone',
            self.test_resource.properties.get(
                zone.DesignateZone.DESCRIPTION))
        self.assertEqual(
            3600,
            self.test_resource.properties.get(zone.DesignateZone.TTL))
        self.assertEqual(
            'abc@test-zone.com',
            self.test_resource.properties.get(zone.DesignateZone.EMAIL))

        self.assertEqual(
            'PRIMARY',
            self.test_resource.properties.get(zone.DesignateZone.TYPE))

        self.assertEqual(
            [],
            self.test_resource.properties.get(zone.DesignateZone.MASTERS))

        self.test_resource.data_set = mock.Mock()
        self.test_resource.handle_create()

        args = dict(
            name='test-zone.com',
            description='Test zone',
            ttl=3600,
            email='abc@test-zone.com',
            type_='PRIMARY'
        )

        mock_zone_create.assert_called_once_with(**args)
        # validate physical resource id
        self.assertEqual(mock_resource['id'], self.test_resource.resource_id)

    def _mock_check_status_active(self):
        self.test_client.zones.get.side_effect = [
            {'status': 'PENDING'},
            {'status': 'ACTIVE'},
            {'status': 'ERROR'}
        ]

    def test_check_create_complete(self):
        self._mock_check_status_active()
        self.assertFalse(self.test_resource.check_create_complete())
        self.assertTrue(self.test_resource.check_create_complete())
        ex = self.assertRaises(exception.ResourceInError,
                               self.test_resource.check_create_complete)
        self.assertIn('Error in zone',
                      ex.message)

    def _test_resource_validate(self, type_, prp):
        def _side_effect(key):
            if key == prp:
                return None
            if key == zone.DesignateZone.TYPE:
                return type_
            else:
                return sample_template['resources'][
                    'test_resource']['properties'][key]

        self.test_resource.properties = mock.MagicMock()
        self.test_resource.properties.get.side_effect = _side_effect
        self.test_resource.properties.__getitem__.side_effect = _side_effect

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.test_resource.validate)
        self.assertEqual('Property %s is required for zone type %s' %
                         (prp, type_),
                         ex.message)

    def test_resource_validate_primary(self):
        self._test_resource_validate(zone.DesignateZone.PRIMARY,
                                     zone.DesignateZone.EMAIL)

    def test_resource_validate_secondary(self):
        self._test_resource_validate(zone.DesignateZone.SECONDARY,
                                     zone.DesignateZone.MASTERS)

    def test_resource_handle_update(self):
        mock_zone_update = self.test_client.zones.update
        self.test_resource.resource_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

        prop_diff = {zone.DesignateZone.EMAIL: 'xyz@test-zone.com',
                     zone.DesignateZone.DESCRIPTION: 'updated description',
                     zone.DesignateZone.TTL: 4200}

        self.test_resource.handle_update(json_snippet=None,
                                         tmpl_diff=None,
                                         prop_diff=prop_diff)

        args = dict(
            description='updated description',
            ttl=4200,
            email='xyz@test-zone.com'
        )
        mock_zone_update.assert_called_once_with(
            self.test_resource.resource_id,
            args)

    def test_check_update_complete(self):
        self._mock_check_status_active()
        self.assertFalse(self.test_resource.check_update_complete())
        self.assertTrue(self.test_resource.check_update_complete())
        ex = self.assertRaises(exception.ResourceInError,
                               self.test_resource.check_update_complete)
        self.assertIn('Error in zone',
                      ex.message)

    def test_check_delete_complete(self):
        self._mock_check_status_active()
        self.assertFalse(self.test_resource.check_delete_complete(
            self._get_mock_resource()['id']
        ))
        self.assertTrue(self.test_resource.check_delete_complete(
            self._get_mock_resource()['id']
        ))
        ex = self.assertRaises(exception.ResourceInError,
                               self.test_resource.check_delete_complete,
                               self._get_mock_resource()['id'])
        self.assertIn('Error in zone',
                      ex.message)

    def test_resolve_attributes(self):
        mock_zone = self._get_mock_resource()
        self.test_resource.resource_id = mock_zone['id']
        self.test_client.zones.get.return_value = mock_zone
        self.assertEqual(
            mock_zone['serial'],
            self.test_resource._resolve_attribute(zone.DesignateZone.SERIAL))
        self.test_client.zones.get.assert_called_once_with(
            self.test_resource.resource_id
        )
