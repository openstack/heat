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
import collections
import mock
import six

from heat.common import exception
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
        self.volume_type_access = self.cinderclient.volume_type_access
        keystoneclient = self.stack.clients.client_plugin('keystone').client()
        keystoneclient.client = mock.MagicMock()
        keystoneclient.client.projects = mock.MagicMock()
        self.project_list = mock.MagicMock()
        keystoneclient.client.projects.get = self.project_list

    def test_resource_mapping(self):
        mapping = cinder_volume_type.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(cinder_volume_type.CinderVolumeType,
                         mapping['OS::Cinder::VolumeType'])
        self.assertIsInstance(self.my_volume_type,
                              cinder_volume_type.CinderVolumeType)

    def _test_handle_create(self, is_public=True, projects=None):
        value = mock.MagicMock()
        volume_type_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        value.id = volume_type_id
        self.volume_types.create.return_value = value
        self.my_volume_type.t['Properties']['is_public'] = is_public
        if projects:
            self.my_volume_type.t['Properties']['projects'] = projects
            project = collections.namedtuple('Project', ['id'])
            stub_projects = [project(p) for p in projects]
            self.project_list.side_effect = [p for p in stub_projects]
        self.my_volume_type.handle_create()
        self.volume_types.create.assert_called_once_with(
            name='volumeBackend', is_public=is_public, description=None)
        value.set_keys.assert_called_once_with(
            {'volume_backend_name': 'lvmdriver'})
        self.assertEqual(volume_type_id, self.my_volume_type.resource_id)
        if projects:
            calls = []
            for p in projects:
                calls.append(mock.call(volume_type_id, p))
            self.volume_type_access.add_project_access.assert_has_calls(calls)

    def test_volume_type_handle_create_public(self):
        self._test_handle_create()

    def test_volume_type_handle_create_not_public(self):
        self._test_handle_create(is_public=False)

    def test_volume_type_with_projects(self):
        self.cinderclient.volume_api_version = 2
        self._test_handle_create(projects=['id1', 'id2'])

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

    def test_volume_type_update_projects(self):
        self.my_volume_type.resource_id = '8aeaa446459a4d3196bc573fc252800b'
        prop_diff = {'projects': ['id2', 'id3']}

        class Access(object):
            def __init__(self, idx, project):
                self.volume_type_id = idx
                self.project_id = project
                self._info = {'volume_type_id': idx,
                              'project_id': project}

        old_access = [Access(self.my_volume_type.resource_id, 'id1'),
                      Access(self.my_volume_type.resource_id, 'id2')]

        self.patchobject(self.volume_type_access, 'list',
                         return_value=old_access)
        self.patchobject(self.volume_type_access, 'remove_project_access')
        project = collections.namedtuple('Project', ['id'])
        self.project_list.return_value = project('id3')
        self.my_volume_type.handle_update(json_snippet=None,
                                          tmpl_diff=None,
                                          prop_diff=prop_diff)

        self.volume_type_access.remove_project_access.assert_called_once_with(
            self.my_volume_type.resource_id, 'id1')
        self.project_list.assert_called_once_with('id3')
        self.volume_type_access.add_project_access.assert_called_once_with(
            self.my_volume_type.resource_id, 'id3')

    def test_validate_projects_in_v1(self):
        self.my_volume_type.t['Properties']['is_public'] = False
        self.my_volume_type.t['Properties']['projects'] = ['id1']
        self.cinderclient.volume_api_version = 1
        self.stub_KeystoneProjectConstraint()
        ex = self.assertRaises(exception.NotSupported,
                               self.my_volume_type.validate)
        expected = 'Using Cinder API V1, volume type access is not supported.'
        self.assertEqual(expected, six.text_type(ex))

    def test_validate_projects_when_public(self):
        self.my_volume_type.t['Properties']['projects'] = ['id1']
        self.my_volume_type.t['Properties']['is_public'] = True
        self.cinderclient.volume_api_version = 2
        self.stub_KeystoneProjectConstraint()
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.my_volume_type.validate)
        expected = ('Can not specify property "projects" '
                    'if the volume type is public.')
        self.assertEqual(expected, six.text_type(ex))

    def test_validate_projects_when_private(self):
        self.my_volume_type.t['Properties']['projects'] = ['id1']
        self.my_volume_type.t['Properties']['is_public'] = False
        self.cinderclient.volume_api_version = 2
        self.stub_KeystoneProjectConstraint()
        self.assertIsNone(self.my_volume_type.validate())

    def test_volume_type_show_resource(self):
        volume_type_id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        self.my_volume_type.resource_id = volume_type_id
        volume_type = mock.Mock()
        volume_type._info = {'vtype': 'info'}
        self.volume_types.get.return_value = volume_type
        self.assertEqual({'vtype': 'info'},
                         self.my_volume_type.FnGetAtt('show'))
