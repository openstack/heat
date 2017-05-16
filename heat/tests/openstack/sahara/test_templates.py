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
from heat.engine.resources.openstack.sahara import templates as st
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
        shares:
          - id: e45eaabf-9300-42e2-b6eb-9ebc92081f46
            access_level: ro
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
      shares:
        - id: e45eaabf-9300-42e2-b6eb-9ebc92081f46
          access_level: ro
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
        self.patchobject(nova.NovaClientPlugin, 'find_flavor_by_name_or_id'
                         ).return_value = 'someflavorid'
        self.patchobject(neutron.NeutronClientPlugin, '_create')

        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='some_pool_id')
        sahara_mock = mock.MagicMock()
        self.ngt_mgr = sahara_mock.node_group_templates
        self.plugin_mgr = sahara_mock.plugins
        self.patchobject(sahara.SaharaClientPlugin,
                         '_create').return_value = sahara_mock
        self.patchobject(sahara.SaharaClientPlugin, 'validate_hadoop_version'
                         ).return_value = None
        self.fake_ngt = FakeNodeGroupTemplate()

        self.t = template_format.parse(node_group_template)
        self.ngt_props = self.t['resources']['node-group']['properties']

    def _init_ngt(self, template):
        self.stack = utils.parse_stack(template)
        return self.stack['node-group']

    def _create_ngt(self, template):
        ngt = self._init_ngt(template)
        self.ngt_mgr.create.return_value = self.fake_ngt
        scheduler.TaskRunner(ngt.create)()
        self.assertEqual((ngt.CREATE, ngt.COMPLETE), ngt.state)
        self.assertEqual(self.fake_ngt.id, ngt.resource_id)
        return ngt

    def test_ngt_create(self):
        self._create_ngt(self.t)
        args = {
            'name': 'node-group-template',
            'plugin_name': 'vanilla',
            'hadoop_version': '2.3.0',
            'flavor_id': 'someflavorid',
            'description': "",
            'volumes_per_node': 0,
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
            'use_autoconfig': None,
            'shares': [{'id': 'e45eaabf-9300-42e2-b6eb-9ebc92081f46',
                        'access_level': 'ro',
                        'path': None}]
        }
        self.ngt_mgr.create.assert_called_once_with(**args)

    def test_validate_floatingippool_on_neutron_fails(self):
        ngt = self._init_ngt(self.t)
        self.patchobject(
            neutron.NeutronClientPlugin,
            'find_resourceid_by_name_or_id'
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

    def test_validate_flavor_constraint_return_false(self):
        self.t['resources']['node-group']['properties'].pop('floating_ip_pool')
        self.t['resources']['node-group']['properties'].pop('volume_type')
        ngt = self._init_ngt(self.t)
        self.patchobject(nova.FlavorConstraint, 'validate'
                         ).return_value = False
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
        name = self.ngt_mgr.create.call_args[1]['name']
        self.assertIn('-nodegroup-', name)

    def test_ngt_show_resource(self):
        ngt = self._create_ngt(self.t)
        self.ngt_mgr.get.return_value = self.fake_ngt
        self.assertEqual({"ng-template": "info"}, ngt.FnGetAtt('show'))
        self.ngt_mgr.get.assert_called_once_with('some_ng_id')

    def test_validate_node_processes_fails(self):
        ngt = self._init_ngt(self.t)
        plugin_mock = mock.MagicMock()
        plugin_mock.node_processes = {
            "HDFS": ["namenode", "datanode", "secondarynamenode"],
            "JobFlow": ["oozie"]
        }
        self.plugin_mgr.get_version_details.return_value = plugin_mock
        ex = self.assertRaises(exception.StackValidationFailed, ngt.validate)
        self.assertIn("resources.node-group.properties: Plugin vanilla "
                      "doesn't support the following node processes: "
                      "jobtracker. Allowed processes are: ",
                      six.text_type(ex))
        self.assertIn("namenode", six.text_type(ex))
        self.assertIn("datanode", six.text_type(ex))
        self.assertIn("secondarynamenode", six.text_type(ex))
        self.assertIn("oozie", six.text_type(ex))

    def test_update(self):
        ngt = self._create_ngt(self.t)
        props = self.ngt_props.copy()
        props['node_processes'] = ['tasktracker', 'datanode']
        props['name'] = 'new-ng-template'
        rsrc_defn = ngt.t.freeze(properties=props)
        scheduler.TaskRunner(ngt.update, rsrc_defn)()
        args = {'node_processes': ['tasktracker', 'datanode'],
                'name': 'new-ng-template'}
        self.ngt_mgr.update.assert_called_once_with('some_ng_id', **args)
        self.assertEqual((ngt.UPDATE, ngt.COMPLETE), ngt.state)

    def test_get_live_state(self):
        ngt = self._create_ngt(self.t)
        resp = mock.MagicMock()
        resp.to_dict.return_value = {
            'volume_local_to_instance': False,
            'availability_zone': None,
            'updated_at': None,
            'use_autoconfig': True,
            'volumes_per_node': 0,
            'id': '6157755e-dfd3-45b4-a445-36588e5f75ad',
            'security_groups': None,
            'shares': None,
            'node_configs': {},
            'auto_security_group': False,
            'volumes_availability_zone': None,
            'description': '',
            'volume_mount_prefix': '/volumes/disk',
            'plugin_name': 'vanilla',
            'floating_ip_pool': None,
            'is_default': False,
            'image_id': None,
            'volumes_size': 0,
            'is_proxy_gateway': False,
            'is_public': False,
            'hadoop_version': '2.7.1',
            'name': 'cluster-nodetemplate-jlgzovdaivn',
            'tenant_id': '221b4f51e9bd4f659845f657a3051a46',
            'created_at': '2016-01-29T11:08:46',
            'volume_type': None,
            'is_protected': False,
            'node_processes': ['namenode'],
            'flavor_id': '2'}

        self.ngt_mgr.get.return_value = resp
        # Simulate replace translation rule execution.
        ngt.properties.data['flavor'] = '1'

        reality = ngt.get_live_state(ngt.properties)
        expected = {
            'volume_local_to_instance': False,
            'availability_zone': None,
            'use_autoconfig': True,
            'volumes_per_node': 0,
            'security_groups': None,
            'shares': None,
            'node_configs': {},
            'auto_security_group': False,
            'volumes_availability_zone': None,
            'description': '',
            'plugin_name': 'vanilla',
            'floating_ip_pool': None,
            'image_id': None,
            'volumes_size': 0,
            'is_proxy_gateway': False,
            'hadoop_version': '2.7.1',
            'name': 'cluster-nodetemplate-jlgzovdaivn',
            'volume_type': None,
            'node_processes': ['namenode'],
            'flavor': '2'
        }

        self.assertEqual(expected, reality)

        # Make sure that old flavor will return when ids are equal - simulate
        # replace translation rule execution.
        ngt.properties.data['flavor'] = '2'
        reality = ngt.get_live_state(ngt.properties)
        self.assertEqual('2', reality.get('flavor'))


class SaharaClusterTemplateTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaClusterTemplateTest, self).setUp()
        self.patchobject(st.constraints.CustomConstraint, '_is_valid'
                         ).return_value = True
        self.patchobject(neutron.NeutronClientPlugin, '_create')
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='some_network_id')
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

    def _create_ct(self, template):
        ct = self._init_ct(template)
        self.ct_mgr.create.return_value = self.fake_ct
        scheduler.TaskRunner(ct.create)()
        self.assertEqual((ct.CREATE, ct.COMPLETE), ct.state)
        self.assertEqual(self.fake_ct.id, ct.resource_id)
        return ct

    def test_ct_create(self):
        self._create_ct(self.t)
        args = {
            'name': 'test-cluster-template',
            'plugin_name': 'vanilla',
            'hadoop_version': '2.3.0',
            'description': '',
            'default_image_id': None,
            'net_id': 'some_network_id',
            'anti_affinity': None,
            'node_groups': None,
            'cluster_configs': None,
            'use_autoconfig': None,
            'shares': [{'id': 'e45eaabf-9300-42e2-b6eb-9ebc92081f46',
                        'access_level': 'ro',
                        'path': None}]
        }
        self.ct_mgr.create.assert_called_once_with(**args)

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
        name = self.ct_mgr.create.call_args[1]['name']
        self.assertIn('-clustertemplate-', name)

    def test_ct_show_resource(self):
        ct = self._create_ct(self.t)
        self.ct_mgr.get.return_value = self.fake_ct
        self.assertEqual({"cluster-template": "info"}, ct.FnGetAtt('show'))
        self.ct_mgr.get.assert_called_once_with('some_ct_id')

    def test_update(self):
        ct = self._create_ct(self.t)
        rsrc_defn = self.stack.t.resource_definitions(self.stack)[
            'cluster-template']
        props = self.t['resources']['cluster-template']['properties'].copy()
        props['plugin_name'] = 'hdp'
        props['hadoop_version'] = '1.3.2'
        props['name'] = 'new-cluster-template'
        rsrc_defn = rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(ct.update, rsrc_defn)()
        args = {
            'plugin_name': 'hdp',
            'hadoop_version': '1.3.2',
            'name': 'new-cluster-template'
        }
        self.ct_mgr.update.assert_called_once_with('some_ct_id', **args)
        self.assertEqual((ct.UPDATE, ct.COMPLETE), ct.state)

    def test_ct_get_live_state(self):
        ct = self._create_ct(self.t)
        resp = mock.MagicMock()
        resp.to_dict.return_value = {
            'neutron_management_network': 'public',
            'description': '',
            'cluster_configs': {},
            'created_at': '2016-01-29T11:45:47',
            'default_image_id': None,
            'updated_at': None,
            'plugin_name': 'vanilla',
            'shares': None,
            'is_default': False,
            'is_protected': False,
            'use_autoconfig': True,
            'anti_affinity': [],
            'tenant_id': '221b4f51e9bd4f659845f657a3051a46',
            'node_groups': [{'volume_local_to_instance': False,
                             'availability_zone': None,
                             'updated_at': None,
                             'node_group_template_id': '1234',
                             'volumes_per_node': 0,
                             'id': '48c356f6-bbe1-4b26-a90a-f3d543c2ea4c',
                             'security_groups': None,
                             'shares': None,
                             'node_configs': {},
                             'auto_security_group': False,
                             'volumes_availability_zone': None,
                             'volume_mount_prefix': '/volumes/disk',
                             'floating_ip_pool': None,
                             'image_id': None,
                             'volumes_size': 0,
                             'is_proxy_gateway': False,
                             'count': 1,
                             'name': 'test',
                             'created_at': '2016-01-29T11:45:47',
                             'volume_type': None,
                             'node_processes': ['namenode'],
                             'flavor_id': '2',
                             'use_autoconfig': True}],
            'is_public': False,
            'hadoop_version': '2.7.1',
            'id': 'c07b8c63-b944-47f9-8588-085547a45c1b',
            'name': 'cluster-template-ykokor6auha4'}

        self.ct_mgr.get.return_value = resp

        reality = ct.get_live_state(ct.properties)
        expected = {
            'neutron_management_network': 'public',
            'description': '',
            'cluster_configs': {},
            'default_image_id': None,
            'plugin_name': 'vanilla',
            'shares': None,
            'anti_affinity': [],
            'node_groups': [{'node_group_template_id': '1234',
                             'count': 1,
                             'name': 'test'}],
            'hadoop_version': '2.7.1',
            'name': 'cluster-template-ykokor6auha4'
        }

        self.assertEqual(set(expected.keys()), set(reality.keys()))
        expected_node_group = sorted(expected.pop('node_groups'))
        reality_node_group = sorted(reality.pop('node_groups'))
        for i in range(len(expected_node_group)):
            self.assertEqual(expected_node_group[i], reality_node_group[i])
        self.assertEqual(expected, reality)
