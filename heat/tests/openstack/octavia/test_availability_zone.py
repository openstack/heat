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

from unittest import mock

from heat.common import template_format
from heat.engine.resources.openstack.octavia import availability_zone
from heat.tests import common
from heat.tests.openstack.octavia import inline_templates
from heat.tests import utils


class AvailabilityZoneTest(common.HeatTestCase):

    def test_resource_mapping(self):
        mapping = availability_zone.resource_mapping()
        self.assertEqual(
            availability_zone.AvailabilityZone,
            mapping['OS::Octavia::AvailabilityZone'],
        )

    def _create_stack(self, tmpl=inline_templates.AVAILABILITY_ZONE_TEMPLATE):
        self.t = template_format.parse(tmpl)
        self.stack = utils.parse_stack(self.t)
        self.az = self.stack['availability_zone']

        self.octavia_client = mock.MagicMock()
        self.az.client = mock.MagicMock()
        self.az.client.return_value = self.octavia_client

        self.az.client_plugin().client = mock.MagicMock(
            return_value=self.octavia_client)

        self.az.resource_id_set('1234')
        self.patchobject(
            self.az, 'physical_resource_name', return_value='resource_name'
        )

    def test_create(self):
        self._create_stack()
        expected = {
            'availability_zone': {
                'description': 'my availability zone',
                'enabled': True,
                'name': 'test_availability_zone',
                'availability_zone_profile_id': 'az_profile_id_1234',
            }
        }

        self.az.handle_create()

        self.octavia_client.availabilityzone_create.assert_called_with(
            json=expected
        )

    def test_show_resource(self):
        self._create_stack()
        self.octavia_client.availabilityzone_show.return_value = {
            'id': 'az_id_1234'
        }
        self.assertEqual({'id': 'az_id_1234'}, self.az._show_resource())

        self.octavia_client.availabilityzone_show.assert_called_with('1234')

    def test_update(self):
        self._create_stack()
        prop_diff = {
            'name': 'test_name2',
            'description': 'test_description2',
            'enabled': False,
        }

        self.az.handle_update(None, None, prop_diff)

        self.octavia_client.availabilityzone_set.assert_called_once_with(
            '1234', json={'availability_zone': prop_diff}
        )

        self.octavia_client.availabilityzone_set.reset_mock()

        # Updating an availability zone with None as name should use
        # physical_resource_name() as new name
        prop_diff = {
            'name': None,
            'description': 'test_description3',
            'enabled': True,
        }

        self.az.handle_update(None, None, prop_diff)

        self.assertEqual(prop_diff['name'], 'resource_name')
        self.octavia_client.availabilityzone_set.assert_called_once_with(
            '1234', json={'availability_zone': prop_diff}
        )

    def test_delete(self):
        self._create_stack()

        self.az.handle_delete()

        self.octavia_client.availabilityzone_delete.assert_called_with('1234')
