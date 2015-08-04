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

from heat.engine.resources.openstack.cinder import cinder_volume_type
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

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

        self.stack = stack.Stack(
            self.ctx, 'cinder_volume_type_test_stack',
            template.Template(volume_type_template)
        )

        self.my_volume_type = self.stack['my_volume_type']
        cinder = mock.MagicMock()
        self.cinderclient = mock.MagicMock()
        self.my_volume_type.client = cinder
        cinder.return_value = self.cinderclient
        self.volume_types = self.cinderclient.volume_types

    def test_resource_mapping(self):
        mapping = cinder_volume_type.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(cinder_volume_type.CinderVolumeType,
                         mapping['OS::Cinder::VolumeType'])
        self.assertIsInstance(self.my_volume_type,
                              cinder_volume_type.CinderVolumeType)

    def _test_handle_create(self, is_public=True):
        value = mock.MagicMock()
        volume_type_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        value.id = volume_type_id
        self.volume_types.create.return_value = value
        self.my_volume_type.t['Properties']['is_public'] = is_public
        self.my_volume_type.handle_create()
        self.volume_types.create.assert_called_once_with(
            name='volumeBackend', is_public=is_public, description=None)
        value.set_keys.assert_called_once_with(
            {'volume_backend_name': 'lvmdriver'})
        self.assertEqual(volume_type_id, self.my_volume_type.resource_id)

    def test_volume_type_handle_create_public(self):
        self._test_handle_create()

    def test_volume_type_handle_create_not_public(self):
        self._test_handle_create(is_public=False)

    def _test_update(self, update_args, is_update_metadata=False):
        if is_update_metadata:
            value = mock.MagicMock()
            self.volume_types.get.return_value = value
            value.get_keys.return_value = {'volume_backend_name': 'lvmdriver'}
        else:
            volume_type_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
            self.my_volume_type.resource_id = volume_type_id

        self.my_volume_type.handle_update(json_snippet=None,
                                          tmpl_diff=None,
                                          prop_diff=update_args)
        if is_update_metadata:
            value.unset_keys.assert_called_once_with(
                {'volume_backend_name': 'lvmdriver'})
            value.set_keys.assert_called_once_with(
                update_args['metadata'])
        else:
            self.volume_types.update.assert_called_once_with(
                volume_type_id, **update_args)

    def test_volume_type_handle_update_description(self):
        update_args = {'description': 'update'}
        self._test_update(update_args)

    def test_volume_type_handle_update_name(self):
        update_args = {'name': 'update'}
        self._test_update(update_args)

    def test_volume_type_handle_update_metadata(self):
        new_keys = {'volume_backend_name': 'lvmdriver',
                    'capabilities:replication': 'True'}
        prop_diff = {'metadata': new_keys}
        self._test_update(prop_diff, is_update_metadata=True)

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

    def test_volume_type_show_resource(self):
        volume_type_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        self.my_volume_type.resource_id = volume_type_id
        volume_type = mock.Mock()
        volume_type._info = {'vtype': 'info'}
        self.volume_types.get.return_value = volume_type
        self.assertEqual({'vtype': 'info'},
                         self.my_volume_type.FnGetAtt('show'))
