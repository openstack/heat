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
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import neutron
from heat.engine.clients.os import sahara
from heat.engine.resources.openstack.sahara import cluster as sc
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


cluster_stack_template = """
heat_template_version: 2013-05-23
description: Hadoop Cluster by Sahara
resources:
  super-cluster:
    type: OS::Sahara::Cluster
    properties:
      name: super-cluster
      plugin_name: vanilla
      hadoop_version: 2.3.0
      cluster_template_id: some_cluster_template_id
      default_image_id: some_image
      key_name: admin
      neutron_management_network: some_network
      shares:
        - id: some_share_id
          access_level: ro
"""

# NOTE(jfreud): the resource name contains an invalid character
cluster_stack_template_without_name = """
heat_template_version: 2013-05-23
description: Hadoop Cluster by Sahara
resources:
  lots_of_underscore_name:
    type: OS::Sahara::Cluster
    properties:
      plugin_name: vanilla
      hadoop_version: 2.3.0
      cluster_template_id: some_cluster_template_id
      default_image_id: some_image
      key_name: admin
      neutron_management_network: some_network
      shares:
        - id: some_share_id
          access_level: ro
"""


class FakeCluster(object):
    def __init__(self, status='Active'):
        self.status = status
        self.id = "some_id"
        self.name = "super-cluster"
        self.info = {"HDFS": {"NameNode": "hdfs://hostname:port",
                              "Web UI": "http://host_ip:port"}}
        self.to_dict = lambda: {"cluster": "info"}


class SaharaClusterTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaClusterTest, self).setUp()
        self.patchobject(sc.constraints.CustomConstraint, '_is_valid'
                         ).return_value = True
        self.patchobject(glance.GlanceClientPlugin,
                         'find_image_by_name_or_id'
                         ).return_value = 'some_image_id'
        self.patchobject(neutron.NeutronClientPlugin, '_create')
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='some_network_id')
        self.sahara_mock = mock.MagicMock()
        self.patchobject(sahara.SaharaClientPlugin, '_create'
                         ).return_value = self.sahara_mock
        self.patchobject(sahara.SaharaClientPlugin, 'validate_hadoop_version'
                         ).return_value = None
        self.cl_mgr = self.sahara_mock.clusters
        self.fake_cl = FakeCluster()

        self.t = template_format.parse(cluster_stack_template)
        self.t2 = template_format.parse(cluster_stack_template_without_name)

    def _init_cluster(self, template, name='super-cluster'):
        self.stack = utils.parse_stack(template)
        cluster = self.stack[name]
        return cluster

    def _create_cluster(self, template):
        cluster = self._init_cluster(template)
        self.cl_mgr.create.return_value = self.fake_cl
        self.cl_mgr.get.return_value = self.fake_cl
        scheduler.TaskRunner(cluster.create)()
        self.assertEqual((cluster.CREATE, cluster.COMPLETE),
                         cluster.state)
        self.assertEqual(self.fake_cl.id, cluster.resource_id)
        return cluster

    def test_cluster_create(self):
        self._create_cluster(self.t)
        expected_args = ('super-cluster', 'vanilla', '2.3.0')
        expected_kwargs = {'cluster_template_id': 'some_cluster_template_id',
                           'user_keypair_id': 'admin',
                           'default_image_id': 'some_image_id',
                           'net_id': 'some_network_id',
                           'use_autoconfig': None,
                           'shares': [{'id': 'some_share_id',
                                       'access_level': 'ro',
                                       'path': None}]}
        self.cl_mgr.create.assert_called_once_with(*expected_args,
                                                   **expected_kwargs)
        self.cl_mgr.get.assert_called_once_with(self.fake_cl.id)

    def test_cluster_create_invalid_name(self):
        cluster = self._init_cluster(self.t2, 'lots_of_underscore_name')
        self.cl_mgr.create.return_value = self.fake_cl
        self.cl_mgr.get.return_value = self.fake_cl
        scheduler.TaskRunner(cluster.create)()
        name = self.cl_mgr.create.call_args[0][0]
        self.assertIn('lotsofunderscorename', name)

    def test_cluster_create_fails(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        cluster = self._init_cluster(self.t)
        self.cl_mgr.create.return_value = self.fake_cl
        self.cl_mgr.get.return_value = FakeCluster(status='Error')
        create_task = scheduler.TaskRunner(cluster.create)
        ex = self.assertRaises(exception.ResourceFailure, create_task)
        expected = ('ResourceInError: resources.super-cluster: '
                    'Went to status Error due to "Unknown"')
        self.assertEqual(expected, six.text_type(ex))

    def test_cluster_check_delete_complete_error(self):
        cluster = self._create_cluster(self.t)
        self.cl_mgr.get.side_effect = [
            self.fake_cl,
            sahara.sahara_base.APIException()]
        self.cl_mgr.get.reset_mock()
        delete_task = scheduler.TaskRunner(cluster.delete)
        ex = self.assertRaises(exception.ResourceFailure, delete_task)
        expected = "APIException: resources.super-cluster: None"
        self.assertEqual(expected, six.text_type(ex))
        self.cl_mgr.delete.assert_called_once_with(self.fake_cl.id)
        self.assertEqual(2, self.cl_mgr.get.call_count)

    def test_cluster_delete_cluster_in_error(self):
        cluster = self._create_cluster(self.t)
        self.cl_mgr.get.side_effect = [
            self.fake_cl,
            FakeCluster(status='Error')]
        self.cl_mgr.get.reset_mock()
        delete_task = scheduler.TaskRunner(cluster.delete)
        ex = self.assertRaises(exception.ResourceFailure, delete_task)
        expected = ('ResourceInError: resources.super-cluster: '
                    'Went to status Error due to "Unknown"')
        self.assertEqual(expected, six.text_type(ex))
        self.cl_mgr.delete.assert_called_once_with(self.fake_cl.id)
        self.assertEqual(2, self.cl_mgr.get.call_count)

    def test_cluster_resolve_attribute(self):
        cluster = self._create_cluster(self.t)
        self.cl_mgr.get.reset_mock()
        self.assertEqual(self.fake_cl.info,
                         cluster._resolve_attribute('info'))
        self.assertEqual(self.fake_cl.status,
                         cluster._resolve_attribute('status'))
        self.assertEqual({"cluster": "info"}, cluster.FnGetAtt('show'))
        self.assertEqual(3, self.cl_mgr.get.call_count)

    def test_cluster_create_no_image_anywhere_fails(self):
        self.t['resources']['super-cluster']['properties'].pop(
            'default_image_id')
        self.sahara_mock.cluster_templates.get.return_value = mock.Mock(
            default_image_id=None)
        cluster = self._init_cluster(self.t)
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(cluster.create))
        self.assertIsInstance(ex.exc, exception.StackValidationFailed)
        self.assertIn("default_image_id must be provided: "
                      "Referenced cluster template some_cluster_template_id "
                      "has no default_image_id defined.",
                      six.text_type(ex.message))

    def test_cluster_validate_no_network_on_neutron_fails(self):
        self.t['resources']['super-cluster']['properties'].pop(
            'neutron_management_network')
        cluster = self._init_cluster(self.t)
        ex = self.assertRaises(exception.StackValidationFailed,
                               cluster.validate)
        error_msg = ('Property error: resources.super-cluster.properties: '
                     'Property neutron_management_network not assigned')
        self.assertEqual(error_msg, six.text_type(ex))

    def test_deprecated_properties_correctly_translates(self):
        tmpl = '''
heat_template_version: 2013-05-23
description: Hadoop Cluster by Sahara
resources:
  super-cluster:
    type: OS::Sahara::Cluster
    properties:
      name: super-cluster
      plugin_name: vanilla
      hadoop_version: 2.3.0
      cluster_template_id: some_cluster_template_id
      image: some_image
      key_name: admin
      neutron_management_network: some_network
      '''
        ct = self._create_cluster(template_format.parse(tmpl))
        self.assertEqual('some_image_id',
                         ct.properties.get('default_image_id'))
        self.assertIsNone(ct.properties.get('image_id'))
