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
from neutronclient.neutron import v2_0 as neutronV20
from openstack import exceptions
from oslo_utils import excutils
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine import rsrc_defn
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class NeutronSegmentTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronSegmentTest, self).setUp()

        self.ctx = utils.dummy_context()
        tpl = template_format.parse(inline_templates.SEGMENT_TEMPLATE)
        self.stack = stack.Stack(
            self.ctx,
            'segment_test',
            template.Template(tpl)
        )

        class FakeOpenStackPlugin(object):

            @excutils.exception_filter
            def ignore_not_found(self, ex):
                if not isinstance(ex, exceptions.ResourceNotFound):
                    raise ex

        self.sdkclient = mock.Mock()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.patchobject(excutils.exception_filter, '__exit__')
        self.segment = self.stack['segment']
        self.segment.client = mock.Mock(return_value=self.sdkclient)
        self.segment.client_plugin = mock.Mock(
            return_value=FakeOpenStackPlugin())
        self.patchobject(self.segment, 'physical_resource_name',
                         return_value='test_segment')
        self.patchobject(neutronV20, 'find_resourceid_by_name_or_id',
                         return_value='private')

    def test_segment_handle_create(self):
        seg = mock.Mock(id='9c1eb3fe-7bba-479d-bd43-1d497e53c384')
        create_props = {'name': 'test_segment',
                        'network_id': 'private',
                        'network_type': 'vxlan',
                        'segmentation_id': 101}

        mock_create = self.patchobject(self.sdkclient.network,
                                       'create_segment',
                                       return_value=seg)
        self.segment.handle_create()
        self.assertEqual('9c1eb3fe-7bba-479d-bd43-1d497e53c384',
                         self.segment.resource_id)
        mock_create.assert_called_once_with(**create_props)

    def test_segment_handle_delete(self):
        segment_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.segment.resource_id = segment_id
        mock_delete = self.patchobject(self.sdkclient.network,
                                       'delete_segment',
                                       return_value=None)
        self.assertIsNone(self.segment.handle_delete())
        mock_delete.assert_called_once_with(self.segment.resource_id)

    def test_segment_handle_delete_not_found(self):
        segment_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.segment.resource_id = segment_id
        mock_delete = self.patchobject(
            self.sdkclient.network, 'delete_segment',
            side_effect=exceptions.ResourceNotFound)
        self.assertIsNone(self.segment.handle_delete())
        mock_delete.assert_called_once_with(self.segment.resource_id)

    def test_segment_delete_resource_id_is_none(self):
        self.segment.resource_id = None
        mock_delete = self.patchobject(self.sdkclient.network,
                                       'delete_segment')
        self.assertIsNone(self.segment.handle_delete())
        self.assertEqual(0, mock_delete.call_count)

    def test_segment_handle_update(self):
        segment_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.segment.resource_id = segment_id

        props = {
            'name': 'test_segment',
            'description': 'updated'
        }
        mock_update = self.patchobject(self.sdkclient.network,
                                       'update_segment')
        update_dict = props.copy()
        update_snippet = rsrc_defn.ResourceDefinition(
            self.segment.name,
            self.segment.type(),
            props)

        # with name
        self.segment.handle_update(
            json_snippet=update_snippet,
            tmpl_diff={},
            prop_diff=props)

        # without name
        props['name'] = None
        self.segment.handle_update(
            json_snippet=update_snippet,
            tmpl_diff={},
            prop_diff=props)
        self.assertEqual(2, mock_update.call_count)
        mock_update.assert_called_with(segment_id, **update_dict)

    def test_validate_vlan_type(self):
        self.t = template_format.parse(inline_templates.SEGMENT_TEMPLATE)
        props = self.t['resources']['segment']['properties']
        props['network_type'] = 'vlan'
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['segment']
        errMsg = 'physical_network is required for vlan provider network.'
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(errMsg, six.text_type(error))

        props['physical_network'] = 'physnet'
        props['segmentation_id'] = '4095'
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['segment']
        errMsg = ('Up to 4094 VLAN network segments can exist '
                  'on each physical_network.')
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(errMsg, six.text_type(error))

    def test_validate_flat_type(self):
        self.t = template_format.parse(inline_templates.SEGMENT_TEMPLATE)
        props = self.t['resources']['segment']['properties']
        props['network_type'] = 'flat'
        props['physical_network'] = 'physnet'
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['segment']
        errMsg = ('segmentation_id is prohibited for flat provider network.')
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(errMsg, six.text_type(error))

    def test_validate_tunnel_type(self):
        self.t = template_format.parse(inline_templates.SEGMENT_TEMPLATE)
        props = self.t['resources']['segment']['properties']
        props['network_type'] = 'vxlan'
        props['physical_network'] = 'physnet'
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['segment']
        errMsg = ('physical_network is prohibited for vxlan provider network.')
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(errMsg, six.text_type(error))

    def test_segment_get_attr(self):
        segment_id = '477e8273-60a7-4c41-b683-fdb0bc7cd151'
        self.segment.resource_id = segment_id

        seg = {'name': 'test_segment',
               'id': '477e8273-60a7-4c41-b683-fdb0bc7cd151',
               'network_type': 'vxlan',
               'network_id': 'private',
               'segmentation_id': 101}

        class FakeSegment(object):
            def to_dict(self):
                return seg

        get_mock = self.patchobject(self.sdkclient.network, 'get_segment',
                                    return_value=FakeSegment())
        self.assertEqual(seg,
                         self.segment.FnGetAtt('show'))
        get_mock.assert_called_once_with(self.segment.resource_id)

    def test_needs_replace_failed(self):
        self.stack.store()
        self.segment.state_set(self.segment.CREATE, self.segment.FAILED)
        side_effect = [exceptions.ResourceNotFound, 'attr']
        mock_show_resource = self.patchobject(self.segment, '_show_resource',
                                              side_effect=side_effect)
        self.segment.resource_id = None
        self.assertTrue(self.segment.needs_replace_failed())
        self.assertEqual(0, mock_show_resource.call_count)

        self.segment.resource_id = 'seg_id'
        self.assertTrue(self.segment.needs_replace_failed())
        self.assertEqual(1, mock_show_resource.call_count)

        self.assertFalse(self.segment.needs_replace_failed())
        self.assertEqual(2, mock_show_resource.call_count)
