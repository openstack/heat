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

from heat.engine.clients.os import cinder as c_plugin
from heat.engine.resources.openstack.cinder import qos_specs
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

QOS_SPECS_TEMPLATE = {
    'heat_template_version': '2015-10-15',
    'description':  'Cinder QoS specs creation example',
    'resources': {
        'my_qos_specs': {
            'type': 'OS::Cinder::QoSSpecs',
            'properties': {
                'name': 'foobar',
                'specs': {"foo": "bar", "foo1": "bar1"}
            }
        }
    }
}

QOS_ASSOCIATE_TEMPLATE = {
    'heat_template_version': '2015-10-15',
    'description':  'Cinder QoS specs association example',
    'resources': {
        'my_qos_associate': {
            'type': 'OS::Cinder::QoSAssociation',
            'properties': {
                'volume_types': ['ceph', 'lvm'],
                'qos_specs': 'foobar'
            }
        }
    }
}


class QoSSpecsTest(common.HeatTestCase):

    def setUp(self):
        super(QoSSpecsTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.patchobject(c_plugin.CinderClientPlugin, 'has_extension',
                         return_value=True)
        self.stack = stack.Stack(
            self.ctx, 'cinder_qos_spec_test_stack',
            template.Template(QOS_SPECS_TEMPLATE)
        )
        self.my_qos_specs = self.stack['my_qos_specs']
        cinder_client = mock.MagicMock()
        self.cinderclient = mock.MagicMock()
        self.my_qos_specs.client = cinder_client
        cinder_client.return_value = self.cinderclient
        self.qos_specs = self.cinderclient.qos_specs
        self.value = mock.MagicMock()
        self.value.id = '927202df-1afb-497f-8368-9c2d2f26e5db'
        self.value.name = 'foobar'
        self.value.specs = {'foo': 'bar', 'foo1': 'bar1'}
        self.qos_specs.create.return_value = self.value

    def test_resource_mapping(self):
        mapping = qos_specs.resource_mapping()
        self.assertEqual(2, len(mapping))
        self.assertEqual(qos_specs.QoSSpecs,
                         mapping['OS::Cinder::QoSSpecs'])
        self.assertIsInstance(self.my_qos_specs,
                              qos_specs.QoSSpecs)

    def _set_up_qos_specs_environment(self):
        self.qos_specs.create.return_value = self.value
        self.my_qos_specs.handle_create()

    def test_qos_specs_handle_create_specs(self):
        self._set_up_qos_specs_environment()
        self.assertEqual(1, self.qos_specs.create.call_count)
        self.assertEqual(self.value.id, self.my_qos_specs.resource_id)

    def test_qos_specs_handle_update_specs(self):
        self._set_up_qos_specs_environment()
        resource_id = self.my_qos_specs.resource_id
        prop_diff = {'specs': {'foo': 'bar', 'bar': 'bar'}}
        set_expected = {'bar': 'bar'}
        unset_expected = ['foo1']

        self.my_qos_specs.handle_update(
            json_snippet=None, tmpl_diff=None, prop_diff=prop_diff
        )
        self.qos_specs.set_keys.assert_called_once_with(
            resource_id,
            set_expected
        )
        self.qos_specs.unset_keys.assert_called_once_with(
            resource_id,
            unset_expected
        )

    def test_qos_specs_handle_delete_specs(self):
        self._set_up_qos_specs_environment()
        resource_id = self.my_qos_specs.resource_id
        self.my_qos_specs.handle_delete()
        self.qos_specs.disassociate_all.assert_called_once_with(resource_id)


class QoSAssociationTest(common.HeatTestCase):

    def setUp(self):
        super(QoSAssociationTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.qos_specs_id = 'foobar'
        self.patchobject(c_plugin.CinderClientPlugin, 'has_extension',
                         return_value=True)
        self.patchobject(c_plugin.CinderClientPlugin, 'get_qos_specs',
                         return_value=self.qos_specs_id)
        self.stack = stack.Stack(
            self.ctx, 'cinder_qos_associate_test_stack',
            template.Template(QOS_ASSOCIATE_TEMPLATE)
        )
        self.my_qos_associate = self.stack['my_qos_associate']
        cinder_client = mock.MagicMock()
        self.cinderclient = mock.MagicMock()
        self.my_qos_associate.client = cinder_client
        cinder_client.return_value = self.cinderclient
        self.qos_specs = self.cinderclient.qos_specs
        self.stub_QoSSpecsConstraint_validate()
        self.stub_VolumeTypeConstraint_validate()

        self.vt_ceph = 'ceph'
        self.vt_lvm = 'lvm'
        self.vt_new_ceph = 'new_ceph'

    def test_resource_mapping(self):
        mapping = qos_specs.resource_mapping()
        self.assertEqual(2, len(mapping))
        self.assertEqual(qos_specs.QoSAssociation,
                         mapping['OS::Cinder::QoSAssociation'])
        self.assertIsInstance(self.my_qos_associate,
                              qos_specs.QoSAssociation)

    def _set_up_qos_associate_environment(self):
        self.my_qos_associate.handle_create()

    def test_qos_associate_handle_create(self):
        self.patchobject(c_plugin.CinderClientPlugin, 'get_volume_type',
                         side_effect=[self.vt_ceph, self.vt_lvm])
        self._set_up_qos_associate_environment()
        self.cinderclient.qos_specs.associate.assert_any_call(
            self.qos_specs_id,
            self.vt_ceph
        )
        self.qos_specs.associate.assert_any_call(
            self.qos_specs_id,
            self.vt_lvm
        )

    def test_qos_associate_handle_update(self):
        self.patchobject(c_plugin.CinderClientPlugin, 'get_volume_type',
                         side_effect=[self.vt_lvm, self.vt_ceph,
                                      self.vt_new_ceph,
                                      self.vt_ceph])
        self._set_up_qos_associate_environment()
        prop_diff = {'volume_types': [self.vt_lvm, self.vt_new_ceph]}
        self.my_qos_associate.handle_update(
            json_snippet=None, tmpl_diff=None, prop_diff=prop_diff
        )
        self.qos_specs.associate.assert_any_call(
            self.qos_specs_id,
            self.vt_new_ceph
        )
        self.qos_specs.disassociate.assert_any_call(
            self.qos_specs_id,
            self.vt_ceph
        )

    def test_qos_associate_handle_delete_specs(self):
        self.patchobject(c_plugin.CinderClientPlugin, 'get_volume_type',
                         side_effect=[self.vt_ceph, self.vt_lvm,
                                      self.vt_ceph, self.vt_lvm])
        self._set_up_qos_associate_environment()
        self.my_qos_associate.handle_delete()
        self.qos_specs.disassociate.assert_any_call(
            self.qos_specs_id,
            self.vt_ceph
        )
        self.qos_specs.disassociate.assert_any_call(
            self.qos_specs_id,
            self.vt_lvm
        )
