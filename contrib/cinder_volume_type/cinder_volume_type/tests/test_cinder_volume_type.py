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

from heat.engine import parser
from heat.engine import resource
from heat.engine import template
from heat.tests import common
from heat.tests import utils

from ..resources.cinder_volume_type import CinderVolumeType  # noqa
from ..resources.cinder_volume_type import resource_mapping  # noqa

volume_type_template = {
    'heat_template_version': '2013-05-23',
    'resources': {
        'my_volume_type': {
            'type': 'OS::Cinder::VolumeType',
            'properties': {
                'name': 'volumeBackend',
                'metadata': {'volume_backend_name': 'lvmdriver'}
            }
        }
    }
}


class CinderVolumeTypeTest(common.HeatTestCase):
    def setUp(self):
        super(CinderVolumeTypeTest, self).setUp()

        self.ctx = utils.dummy_context()

        # For unit testing purpose. Register resource provider
        # explicitly.
        resource._register_class('OS::Cinder::VolumeType', CinderVolumeType)

        self.stack = parser.Stack(
            self.ctx, 'cinder_volume_type_test_stack',
            template.Template(volume_type_template)
        )

        self.my_volume_type = self.stack['my_volume_type']
        cinder = mock.MagicMock()
        self.cinderclient = mock.MagicMock()
        self.my_volume_type.cinder = cinder
        cinder.return_value = self.cinderclient
        self.volume_types = self.cinderclient.volume_types

    def test_resource_mapping(self):
        mapping = resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(CinderVolumeType, mapping['OS::Cinder::VolumeType'])
        self.assertIsInstance(self.my_volume_type, CinderVolumeType)

    def test_volume_type_handle_create(self):
        value = mock.MagicMock()
        volume_type_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        value.id = volume_type_id
        self.volume_types.create.return_value = value
        self.my_volume_type.handle_create()
        value.set_keys.assert_called_once_with(
            {'volume_backend_name': 'lvmdriver'})
        self.assertEqual(volume_type_id, self.my_volume_type.resource_id)

    def test_volume_type_handle_update_matadata(self):
        value = mock.MagicMock()
        self.volume_types.get.return_value = value
        value.get_keys.return_value = {'volume_backend_name': 'lvmdriver'}

        new_keys = {'volume_backend_name': 'lvmdriver',
                    'capabilities:replication': 'True'}
        prop_diff = {'metadata': new_keys}
        self.my_volume_type.handle_update(json_snippet=None,
                                          tmpl_diff=None,
                                          prop_diff=prop_diff)
        value.unset_keys.assert_called_once_with(
            {'volume_backend_name': 'lvmdriver'})
        value.set_keys.assert_called_once_with(new_keys)

    def test_volume_type_handle_delete(self):
        self.resource_id = None
        self.assertIsNone(self.my_volume_type.handle_delete())
        volume_type_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        self.my_volume_type.resource_id = volume_type_id
        self.volume_types.delete.return_value = None
        self.assertIsNone(self.my_volume_type.handle_delete())
        exc = self.cinderclient.HTTPClientError('Not Found.')
        self.volume_types.delete.side_effect = exc
        self.assertIsNone(self.my_volume_type.handle_delete())
