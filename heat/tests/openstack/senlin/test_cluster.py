# Copyright 2015 IBM Corp.
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
from heat.engine.clients.os import senlin
from heat.engine.resources.openstack.senlin import cluster as sc
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils
from senlinclient.common import exc


cluster_stack_template = """
heat_template_version: 2016-04-08
description: Senlin Cluster Template
resources:
  senlin-cluster:
    type: OS::Senlin::Cluster
    properties:
      name: SenlinCluster
      profile: fake_profile
      min_size: 0
      max_size: -1
      desired_capacity: 1
      timeout: 3600
      metadata:
        foo: bar
"""


class FakeCluster(object):
    def __init__(self, id='some_id', status='ACTIVE'):
        self.status = status
        self.status_reason = 'Unknown'
        self.id = id
        self.name = "SenlinCluster"
        self.metadata = {}
        self.nodes = ['node1']
        self.desired_capacity = 1
        self.metadata = {'foo': 'bar'}
        self.timeout = 3600
        self.max_size = -1
        self.min_size = 0

    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'status_reason': self.status_reason,
            'name': self.name,
            'metadata': self.metadata,
            'timeout': self.timeout,
            'desired_capacity': self.desired_capacity,
            'max_size': self.max_size,
            'min_size': self.min_size,
            'nodes': self.nodes
        }


class SenlinClusterTest(common.HeatTestCase):
    def setUp(self):
        super(SenlinClusterTest, self).setUp()
        self.senlin_mock = mock.MagicMock()
        self.patchobject(sc.Cluster, 'client', return_value=self.senlin_mock)
        self.patchobject(senlin.ProfileConstraint, 'validate',
                         return_value=True)
        self.fake_cl = FakeCluster()
        self.t = template_format.parse(cluster_stack_template)

    def _init_cluster(self, template):
        self.stack = utils.parse_stack(template)
        cluster = self.stack['senlin-cluster']
        return cluster

    def _create_cluster(self, template):
        cluster = self._init_cluster(template)
        self.senlin_mock.create_cluster.return_value = self.fake_cl
        self.senlin_mock.get_cluster.return_value = self.fake_cl
        scheduler.TaskRunner(cluster.create)()
        self.assertEqual((cluster.CREATE, cluster.COMPLETE),
                         cluster.state)
        self.assertEqual(self.fake_cl.id, cluster.resource_id)
        return cluster

    def test_resource_mapping(self):
        mapping = sc.resource_mapping()
        self.assertEqual(1, len(mapping))
        self.assertEqual(sc.Cluster,
                         mapping['OS::Senlin::Cluster'])

    def test_cluster_create_success(self):
        self._create_cluster(self.t)
        expect_kwargs = {
            'name': 'SenlinCluster',
            'profile_id': 'fake_profile',
            'desired_capacity': 1,
            'min_size': 0,
            'max_size': -1,
            'metadata': {'foo': 'bar'},
            'timeout': 3600,
        }
        self.senlin_mock.create_cluster.assert_called_once_with(
            **expect_kwargs)
        self.senlin_mock.get_cluster.assert_called_once_with(self.fake_cl.id)

    def test_cluster_create_error(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        cluster = self._init_cluster(self.t)
        self.senlin_mock.create_cluster.return_value = self.fake_cl
        self.senlin_mock.get_cluster.return_value = FakeCluster(
            status='ERROR')
        create_task = scheduler.TaskRunner(cluster.create)
        ex = self.assertRaises(exception.ResourceFailure, create_task)
        expected = ('ResourceInError: resources.senlin-cluster: '
                    'Went to status ERROR due to "Unknown"')
        self.assertEqual(expected, six.text_type(ex))

    def test_cluster_delete_success(self):
        cluster = self._create_cluster(self.t)
        self.senlin_mock.get_cluster.side_effect = [
            exc.HTTPNotFound(),
        ]
        scheduler.TaskRunner(cluster.delete)()
        self.senlin_mock.delete_cluster.assert_called_once_with(
            cluster.resource_id)

    def test_cluster_delete_error(self):
        cluster = self._create_cluster(self.t)
        self.senlin_mock.get_cluster.side_effect = exception.Error('oops')
        delete_task = scheduler.TaskRunner(cluster.delete)
        ex = self.assertRaises(exception.ResourceFailure, delete_task)
        expected = 'Error: resources.senlin-cluster: oops'
        self.assertEqual(expected, six.text_type(ex))

    def test_cluster_resolve_attribute(self):
        excepted_show = {
            'id': 'some_id',
            'status': 'ACTIVE',
            'status_reason': 'Unknown',
            'name': 'SenlinCluster',
            'metadata': {'foo': 'bar'},
            'timeout': 3600,
            'desired_capacity': 1,
            'max_size': -1,
            'min_size': 0,
            'nodes': ['node1']
        }
        cluster = self._create_cluster(self.t)
        self.assertEqual(self.fake_cl.desired_capacity,
                         cluster._resolve_attribute('desired_capacity'))
        self.assertEqual(['node1'],
                         cluster._resolve_attribute('nodes'))
        self.assertEqual(excepted_show,
                         cluster._show_resource())


class TestSenlinClusterValidation(common.HeatTestCase):
    def setUp(self):
        super(TestSenlinClusterValidation, self).setUp()
        self.t = template_format.parse(cluster_stack_template)

    def test_invalid_min_max_size(self):
        self.t['resources']['senlin-cluster']['properties']['min_size'] = 2
        self.t['resources']['senlin-cluster']['properties']['max_size'] = 1
        stack = utils.parse_stack(self.t)
        ex = self.assertRaises(exception.StackValidationFailed,
                               stack['senlin-cluster'].validate)
        self.assertEqual('min_size can not be greater than max_size',
                         six.text_type(ex))

    def test_invalid_desired_capacity(self):
        self.t['resources']['senlin-cluster']['properties']['min_size'] = 1
        self.t['resources']['senlin-cluster']['properties']['max_size'] = 2
        self.t['resources']['senlin-cluster']['properties'][
            'desired_capacity'] = 3
        stack = utils.parse_stack(self.t)
        ex = self.assertRaises(exception.StackValidationFailed,
                               stack['senlin-cluster'].validate)
        self.assertEqual(
            'desired_capacity must be between min_size and max_size',
            six.text_type(ex)
        )
