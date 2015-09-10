# Copyright (c) 2014 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine.clients.os import sahara
from heat.engine.resources.openstack.sahara import sahara_templates as st
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

node_group_template = """
heat_template_version: 2013-05-23
description: Sahara Node Group Template
resources:
  node-group:
    type: OS::Sahara::NodeGroupTemplate
    properties:
        name: node-group-template
        plugin_name: vanilla
        hadoop_version: 2.3.0
        flavor: m1.large
        volume_type: lvm
        floating_ip_pool: some_pool_name
        node_processes:
          - namenode
          - jobtracker
        is_proxy_gateway: True
"""

cluster_template = """
heat_template_version: 2013-05-23
description: Sahara Cluster Template
resources:
  cluster-template:
    type: OS::Sahara::ClusterTemplate
    properties:
      name: test-cluster-template
      plugin_name: vanilla
      hadoop_version: 2.3.0
      neutron_management_network: some_network
"""

cluster_template_without_name = """
heat_template_version: 2013-05-23
resources:
  cluster_template!:
    type: OS::Sahara::ClusterTemplate
    properties:
      plugin_name: vanilla
      hadoop_version: 2.3.0
      neutron_management_network: some_network
"""

node_group_template_without_name = """
heat_template_version: 2013-05-23
resources:
  node_group!:
    type: OS::Sahara::NodeGroupTemplate
    properties:
        plugin_name: vanilla
        hadoop_version: 2.3.0
        flavor: m1.large
        floating_ip_pool: some_pool_name
        node_processes:
          - namenode
          - jobtracker
"""


class FakeNodeGroupTemplate(object):
    def __init__(self):
        self.id = "some_ng_id"
        self.name = "test-cluster-template"
        self.to_dict = lambda: {"ng-template": "info"}


class FakeClusterTemplate(object):
    def __init__(self):
        self.id = "some_ct_id"
        self.name = "node-group-template"
        self.to_dict = lambda: {"cluster-template": "info"}


class SaharaNodeGroupTemplateTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaNodeGroupTemplateTest, self).setUp()
        self.stub_FlavorConstraint_validate()
        self.stub_SaharaPluginConstraint()
        self.stub_VolumeTypeConstraint_validate()
        self.patchobject(nova.NovaClientPlugin, 'get_flavor_id'
                         ).return_value = 'someflavorid'
        self.patchobject(neutron.NeutronClientPlugin, '_create')
        self.patchobject(neutron.NeutronClientPlugin, 'find_neutron_resource'
                         ).return_value = 'some_pool_id'
        sahara_mock = mock.MagicMock()
        self.ngt_mgr = sahara_mock.node_group_templates
        self.patchobject(sahara.SaharaClientPlugin,
                         '_create').return_value = sahara_mock
        self.patchobject(sahara.SaharaClientPlugin, 'validate_hadoop_version'
                         ).return_value = None
        self.fake_ngt = FakeNodeGroupTemplate()

        self.t = template_format.parse(node_group_template)

    def _init_ngt(self, template):
        self.stack = utils.parse_stack(template)
        return self.stack['node-group']

    def test_ngt_resource_mapping(self):
        ngt = self._init_ngt(self.t)
        mapping = st.resource_mapping()
        self.assertEqual(st.SaharaNodeGroupTemplate,
                         mapping['OS::Sahara::NodeGroupTemplate'])
        self.assertIsInstance(ngt,
                              st.SaharaNodeGroupTemplate)

    def _create_ngt(self, template):
        ngt = self._init_ngt(template)
        self.ngt_mgr.create.return_value = self.fake_ngt
        scheduler.TaskRunner(ngt.create)()
        self.assertEqual((ngt.CREATE, ngt.COMPLETE), ngt.state)
        self.assertEqual(self.fake_ngt.id, ngt.resource_id)
        return ngt

    def test_ngt_create(self):
        self._create_ngt(self.t)
        expected_args = ('node-group-template', 'vanilla',
                         '2.3.0', 'someflavorid')
        expected_kwargs = {'description': "",
                           'volumes_per_node': None,
                           'volumes_size': None,
                           'volume_type': 'lvm',
                           'security_groups': None,
                           'auto_security_group': None,
                           'availability_zone': None,
                           'volumes_availability_zone': None,
                           'node_processes': ['namenode', 'jobtracker'],
                           'floating_ip_pool': 'some_pool_id',
                           'node_configs': None,
                           'image_id': None,
                           'is_proxy_gateway': True,
                           'volume_local_to_instance': None,
                           'use_autoconfig': None
                           }
        self.ngt_mgr.create.assert_called_once_with(*expected_args,
                                                    **expected_kwargs)

    def test_ngt_delete(self):
        ngt = self._create_ngt(self.t)
        scheduler.TaskRunner(ngt.delete)()
        self.ngt_mgr.delete.assert_called_once_with(self.fake_ngt.id)
        self.assertEqual((ngt.DELETE, ngt.COMPLETE), ngt.state)

    def test_ngt_delete_ignores_not_found(self):
        ngt = self._create_ngt(self.t)
        self.ngt_mgr.delete.side_effect = sahara.sahara_base.APIException(
            error_code=404)
        scheduler.TaskRunner(ngt.delete)()
        self.ngt_mgr.delete.assert_called_once_with(self.fake_ngt.id)

    def test_ngt_delete_fails(self):
        ngt = self._create_ngt(self.t)
        self.ngt_mgr.delete.side_effect = sahara.sahara_base.APIException()
        delete_task = scheduler.TaskRunner(ngt.delete)
        ex = self.assertRaises(exception.ResourceFailure, delete_task)
        expected = "APIException: resources.node-group: None"
        self.assertEqual(expected, six.text_type(ex))
        self.ngt_mgr.delete.assert_called_once_with(self.fake_ngt.id)

    def test_validate_floatingippool_on_neutron_fails(self):
        ngt = self._init_ngt(self.t)
        self.patchobject(ngt, 'is_using_neutron').return_value = True

        self.patchobject(
            neutron.NeutronClientPlugin, 'find_neutron_resource'
        ).side_effect = [
            neutron.exceptions.NeutronClientNoUniqueMatch(message='Too many'),
            neutron.exceptions.NeutronClientException(message='Not found',
                                                      status_code=404)
        ]
        ex = self.assertRaises(exception.StackValidationFailed, ngt.validate)
        self.assertEqual('Too many',
                         six.text_type(ex))
        ex = self.assertRaises(exception.StackValidationFailed, ngt.validate)
        self.assertEqual('Not found',
                         six.text_type(ex))

    def test_validate_floatingippool_on_novanetwork_fails(self):
        ngt = self._init_ngt(self.t)
        self.patchobject(ngt, 'is_using_neutron').return_value = False
        nova_mock = mock.MagicMock()
        nova_mock.floating_ip_pools.find.side_effect = (
            nova.exceptions.NotFound(404, message='Not found'))
        self.patchobject(nova.NovaClientPlugin,
                         '_create').return_value = nova_mock
        ex = self.assertRaises(exception.StackValidationFailed, ngt.validate)
        self.assertEqual('Not found', six.text_type(ex))

    def test_validate_flavor_constraint_return_false(self):
        self.t['resources']['node-group']['properties'].pop('floating_ip_pool')
        self.t['resources']['node-group']['properties'].pop('volume_type')
        ngt = self._init_ngt(self.t)
        self.patchobject(nova.FlavorConstraint, 'validate'
                         ).return_value = False
        self.patchobject(ngt, 'is_using_neutron').return_value = False

        ex = self.assertRaises(exception.StackValidationFailed, ngt.validate)
        self.assertEqual(u"Property error: "
                         u"resources.node-group.properties.flavor: "
                         u"Error validating value 'm1.large'",
                         six.text_type(ex))

    def test_template_invalid_name(self):
        tmpl = template_format.parse(node_group_template_without_name)
        stack = utils.parse_stack(tmpl)
        ngt = stack['node_group!']
        self.ngt_mgr.create.return_value = self.fake_ngt
        scheduler.TaskRunner(ngt.create)()
        self.assertEqual((ngt.CREATE, ngt.COMPLETE), ngt.state)
        self.assertEqual(self.fake_ngt.id, ngt.resource_id)
        name = self.ngt_mgr.create.call_args[0][0]
        self.assertIn('-nodegroup-', name)

    def test_ngt_show_resource(self):
        ngt = self._create_ngt(self.t)
        self.ngt_mgr.get.return_value = self.fake_ngt
        self.assertEqual({"ng-template": "info"}, ngt.FnGetAtt('show'))
        self.ngt_mgr.get.assert_called_once_with('some_ng_id')


class SaharaClusterTemplateTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaClusterTemplateTest, self).setUp()
        self.patchobject(st.constraints.CustomConstraint, '_is_valid'
                         ).return_value = True
        self.patchobject(neutron.NeutronClientPlugin, '_create')
        self.patchobject(neutron.NeutronClientPlugin, 'find_neutron_resource'
                         ).return_value = 'some_network_id'
        sahara_mock = mock.MagicMock()
        self.ct_mgr = sahara_mock.cluster_templates
        self.patchobject(sahara.SaharaClientPlugin,
                         '_create').return_value = sahara_mock
        self.patchobject(sahara.SaharaClientPlugin, 'validate_hadoop_version'
                         ).return_value = None
        self.fake_ct = FakeClusterTemplate()

        self.t = template_format.parse(cluster_template)

    def _init_ct(self, template):
        self.stack = utils.parse_stack(template)
        return self.stack['cluster-template']

    def test_ct_resource_mapping(self):
        ct = self._init_ct(self.t)
        mapping = st.resource_mapping()
        self.assertEqual(st.SaharaClusterTemplate,
                         mapping['OS::Sahara::ClusterTemplate'])
        self.assertIsInstance(ct,
                              st.SaharaClusterTemplate)

    def _create_ct(self, template):
        ct = self._init_ct(template)
        self.ct_mgr.create.return_value = self.fake_ct
        scheduler.TaskRunner(ct.create)()
        self.assertEqual((ct.CREATE, ct.COMPLETE), ct.state)
        self.assertEqual(self.fake_ct.id, ct.resource_id)
        return ct

    def test_ct_create(self):
        self._create_ct(self.t)
        expected_args = ('test-cluster-template', 'vanilla',
                         '2.3.0')
        expected_kwargs = {'description': '',
                           'default_image_id': None,
                           'net_id': 'some_network_id',
                           'anti_affinity': None,
                           'node_groups': None,
                           'cluster_configs': None,
                           'use_autoconfig': None
                           }
        self.ct_mgr.create.assert_called_once_with(*expected_args,
                                                   **expected_kwargs)

    def test_ct_delete(self):
        ct = self._create_ct(self.t)
        scheduler.TaskRunner(ct.delete)()
        self.ct_mgr.delete.assert_called_once_with(self.fake_ct.id)
        self.assertEqual((ct.DELETE, ct.COMPLETE), ct.state)

    def test_ngt_delete_ignores_not_found(self):
        ct = self._create_ct(self.t)
        self.ct_mgr.delete.side_effect = sahara.sahara_base.APIException(
            error_code=404)
        scheduler.TaskRunner(ct.delete)()
        self.ct_mgr.delete.assert_called_once_with(self.fake_ct.id)

    def test_ngt_delete_fails(self):
        ct = self._create_ct(self.t)
        self.ct_mgr.delete.side_effect = sahara.sahara_base.APIException()
        delete_task = scheduler.TaskRunner(ct.delete)
        ex = self.assertRaises(exception.ResourceFailure, delete_task)
        expected = "APIException: resources.cluster-template: None"
        self.assertEqual(expected, six.text_type(ex))
        self.ct_mgr.delete.assert_called_once_with(self.fake_ct.id)

    def test_ct_validate_no_network_on_neutron_fails(self):
        self.t['resources']['cluster-template']['properties'].pop(
            'neutron_management_network')
        ct = self._init_ct(self.t)
        self.patchobject(ct, 'is_using_neutron', return_value=True)
        ex = self.assertRaises(exception.StackValidationFailed,
                               ct.validate)
        self.assertEqual("neutron_management_network must be provided",
                         six.text_type(ex))

    def test_template_invalid_name(self):
        tmpl = template_format.parse(cluster_template_without_name)
        stack = utils.parse_stack(tmpl)
        ct = stack['cluster_template!']
        self.ct_mgr.create.return_value = self.fake_ct
        scheduler.TaskRunner(ct.create)()
        self.assertEqual((ct.CREATE, ct.COMPLETE), ct.state)
        self.assertEqual(self.fake_ct.id, ct.resource_id)
        name = self.ct_mgr.create.call_args[0][0]
        self.assertIn('-clustertemplate-', name)

    def test_ct_show_resource(self):
        ct = self._create_ct(self.t)
        self.ct_mgr.get.return_value = self.fake_ct
        self.assertEqual({"cluster-template": "info"}, ct.FnGetAtt('show'))
        self.ct_mgr.get.assert_called_once_with('some_ct_id')
