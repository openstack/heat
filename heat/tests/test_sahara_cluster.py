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
from oslo.config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import neutron
from heat.engine.clients.os import sahara
from heat.engine.resources import sahara_cluster as sc
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
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
      image: some_image
      key_name: admin
      neutron_management_network: some_network
"""


class FakeCluster(object):
    def __init__(self, status='Active'):
        self.status = status
        self.id = "some_id"
        self.name = "super-cluster"
        self.info = {"HDFS": {"NameNode": "hdfs://hostname:port",
                              "Web UI": "http://host_ip:port"}}


class SaharaClusterTest(HeatTestCase):
    def setUp(self):
        super(SaharaClusterTest, self).setUp()
        self.patchobject(sc.constraints.CustomConstraint, '_is_valid'
                         ).return_value = True
        self.patchobject(glance.GlanceClientPlugin, 'get_image_id'
                         ).return_value = 'some_image_id'
        self.patchobject(neutron.NeutronClientPlugin, '_create')
        self.patchobject(neutron.NeutronClientPlugin, 'find_neutron_resource'
                         ).return_value = 'some_network_id'
        self.sahara_mock = mock.MagicMock()
        self.patchobject(sahara.SaharaClientPlugin, '_create'
                         ).return_value = self.sahara_mock
        self.cl_mgr = self.sahara_mock.clusters
        self.fake_cl = FakeCluster()

        self.t = template_format.parse(cluster_stack_template)

    def _init_cluster(self, template):
        stack = utils.parse_stack(template)
        cluster = stack['super-cluster']
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
                           'net_id': 'some_network_id'}
        self.cl_mgr.create.assert_called_once_with(*expected_args,
                                                   **expected_kwargs)
        self.cl_mgr.get.assert_called_once_with(self.fake_cl.id)

    def test_cluster_delete(self):
        cluster = self._create_cluster(self.t)
        scheduler.TaskRunner(cluster.delete)()
        self.assertEqual((cluster.DELETE, cluster.COMPLETE),
                         cluster.state)
        self.cl_mgr.delete.assert_called_once_with(self.fake_cl.id)

    def test_cluster_create_fails(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        cluster = self._init_cluster(self.t)
        self.cl_mgr.create.return_value = self.fake_cl
        self.cl_mgr.get.return_value = FakeCluster(status='Error')
        create_task = scheduler.TaskRunner(cluster.create)
        ex = self.assertRaises(exception.ResourceFailure, create_task)
        expected = 'ResourceInError: Went to status Error due to "Unknown"'
        self.assertEqual(expected, six.text_type(ex))

    def test_cluster_delete_fails(self):
        cluster = self._create_cluster(self.t)
        self.cl_mgr.delete.side_effect = sahara.sahara_base.APIException()
        delete_task = scheduler.TaskRunner(cluster.delete)
        ex = self.assertRaises(exception.ResourceFailure, delete_task)
        expected = "APIException: None"
        self.assertEqual(expected, six.text_type(ex))
        self.cl_mgr.delete.assert_called_once_with(self.fake_cl.id)

    def test_cluster_not_found_in_delete(self):
        cluster = self._create_cluster(self.t)
        self.cl_mgr.delete.side_effect = sahara.sahara_base.APIException(
            error_code=404)
        scheduler.TaskRunner(cluster.delete)()
        self.cl_mgr.delete.assert_called_once_with(self.fake_cl.id)

    def test_cluster_resolve_attribute(self):
        cluster = self._create_cluster(self.t)
        self.cl_mgr.get.reset_mock()
        self.assertEqual(self.fake_cl.info,
                         cluster._resolve_attribute('info'))
        self.assertEqual(self.fake_cl.status,
                         cluster._resolve_attribute('status'))
        self.assertEqual(2, self.cl_mgr.get.call_count)

    def test_cluster_resource_mapping(self):
        cluster = self._init_cluster(self.t)
        mapping = sc.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(sc.SaharaCluster,
                         mapping['OS::Sahara::Cluster'])
        self.assertIsInstance(cluster, sc.SaharaCluster)

    def test_cluster_create_no_image_anywhere_fails(self):
        self.t['resources']['super-cluster']['properties'].pop('image')
        self.sahara_mock.cluster_templates.get.return_value = mock.Mock(
            default_image_id=None)
        cluster = self._init_cluster(self.t)
        ex = self.assertRaises(exception.ResourceFailure,
                               scheduler.TaskRunner(cluster.create))
        self.assertIsInstance(ex.exc, exception.StackValidationFailed)
        self.assertIn("image must be provided: "
                      "Referenced cluster template some_cluster_template_id "
                      "has no default_image_id defined.",
                      six.text_type(ex.message))

    def test_cluster_validate_no_network_on_neutron_fails(self):
        self.t['resources']['super-cluster']['properties'].pop(
            'neutron_management_network')
        cluster = self._init_cluster(self.t)
        self.patchobject(cluster, 'is_using_neutron', return_value=True)
        ex = self.assertRaises(exception.StackValidationFailed,
                               cluster.validate)
        self.assertEqual("neutron_management_network must be provided",
                         six.text_type(ex))
