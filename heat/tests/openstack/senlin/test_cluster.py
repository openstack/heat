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

import copy
import mock
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import senlin
from heat.engine.resources.openstack.senlin import cluster as sc
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils
from openstack import exceptions


cluster_stack_template = """
heat_template_version: 2016-04-08
description: Senlin Cluster Template
resources:
  senlin-cluster:
    type: OS::Senlin::Cluster
    properties:
      name: SenlinCluster
      profile: fake_profile
      policies:
        - policy: fake_policy
          enabled: true
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
        self.location = 'actions/fake-action'
        self.profile_name = 'fake_profile'
        self.profile_id = 'fake_profile_id'

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
            'nodes': self.nodes,
            'profile_name': self.profile_name,
            'profile_id': self.profile_id
        }


class SenlinClusterTest(common.HeatTestCase):
    def setUp(self):
        super(SenlinClusterTest, self).setUp()
        self.senlin_mock = mock.MagicMock()
        self.senlin_mock.get_profile.return_value = mock.Mock(
            id='fake_profile_id'
        )
        self.patchobject(sc.Cluster, 'client', return_value=self.senlin_mock)
        self.patchobject(senlin.SenlinClientPlugin, 'client',
                         return_value=self.senlin_mock)
        self.patchobject(senlin.ProfileConstraint, 'validate',
                         return_value=True)
        self.patchobject(senlin.PolicyConstraint, 'validate',
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
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='SUCCEEDED')
        self.senlin_mock.get_policy.return_value = mock.Mock(
            id='fake_policy_id'
        )
        self.senlin_mock.cluster_policies.return_value = [
            {'policy_id': 'fake_policy_id', 'enabled': True}
        ]
        scheduler.TaskRunner(cluster.create)()
        self.assertEqual((cluster.CREATE, cluster.COMPLETE),
                         cluster.state)
        self.assertEqual(self.fake_cl.id, cluster.resource_id)
        return cluster

    def test_cluster_create_success(self):
        self._create_cluster(self.t)
        create_cluster_kwargs = {
            'name': 'SenlinCluster',
            'profile_id': 'fake_profile_id',
            'desired_capacity': 1,
            'min_size': 0,
            'max_size': -1,
            'metadata': {'foo': 'bar'},
            'timeout': 3600,
        }
        attach_policy_kwargs = {
            'cluster': self.fake_cl.id,
            'policy': 'fake_policy_id',
            'enabled': True
        }
        self.senlin_mock.create_cluster.assert_called_once_with(
            **create_cluster_kwargs)
        self.senlin_mock.cluster_attach_policy.assert_called_once_with(
            **attach_policy_kwargs)

    def test_cluster_create_error(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        cluster = self._init_cluster(self.t)
        self.senlin_mock.create_cluster.return_value = self.fake_cl
        mock_action = mock.MagicMock()
        mock_action.status = 'FAILED'
        mock_action.status_reason = 'oops'
        self.senlin_mock.get_policy.return_value = mock.Mock(
            id='fake_policy_id'
        )
        self.senlin_mock.get_action.return_value = mock_action
        create_task = scheduler.TaskRunner(cluster.create)
        ex = self.assertRaises(exception.ResourceFailure, create_task)
        expected = ('ResourceInError: resources.senlin-cluster: '
                    'Went to status FAILED due to "oops"')
        self.assertEqual(expected, six.text_type(ex))

    def test_cluster_delete_success(self):
        cluster = self._create_cluster(self.t)
        self.senlin_mock.get_cluster.side_effect = [
            exceptions.ResourceNotFound('SenlinCluster'),
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

    def test_cluster_update_profile(self):
        cluster = self._create_cluster(self.t)
        # Mock translate rules
        self.senlin_mock.get_profile.side_effect = [
            mock.Mock(id='new_profile_id'),
            mock.Mock(id='fake_profile_id'),
            mock.Mock(id='new_profile_id'),
        ]
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-cluster']['properties']
        props['profile'] = 'new_profile'
        props['name'] = 'new_name'
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_cluster = rsrc_defns['senlin-cluster']
        self.senlin_mock.update_cluster.return_value = mock.Mock(
            location='/actions/fake-action')
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='SUCCEEDED')
        scheduler.TaskRunner(cluster.update, new_cluster)()
        self.assertEqual((cluster.UPDATE, cluster.COMPLETE), cluster.state)
        cluster_update_kwargs = {
            'profile_id': 'new_profile_id',
            'name': 'new_name'
        }
        self.senlin_mock.update_cluster.assert_called_once_with(
            cluster=self.fake_cl, **cluster_update_kwargs)
        self.assertEqual(3, self.senlin_mock.get_action.call_count)

    def test_cluster_update_desire_capacity(self):
        cluster = self._create_cluster(self.t)
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-cluster']['properties']
        props['desired_capacity'] = 10
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_cluster = rsrc_defns['senlin-cluster']
        self.senlin_mock.cluster_resize.return_value = {
            'action': 'fake-action'}
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='SUCCEEDED')
        scheduler.TaskRunner(cluster.update, new_cluster)()
        self.assertEqual((cluster.UPDATE, cluster.COMPLETE), cluster.state)
        cluster_resize_kwargs = {
            'adjustment_type': 'EXACT_CAPACITY',
            'number': 10
        }
        self.senlin_mock.cluster_resize.assert_called_once_with(
            cluster=cluster.resource_id, **cluster_resize_kwargs)
        self.assertEqual(3, self.senlin_mock.get_action.call_count)

    def test_cluster_update_policy_add_remove(self):
        cluster = self._create_cluster(self.t)
        # Mock translate rules
        self.senlin_mock.get_policy.side_effect = [
            mock.Mock(id='new_policy_id'),
            mock.Mock(id='fake_policy_id'),
            mock.Mock(id='new_policy_id'),
        ]
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-cluster']['properties']
        props['policies'] = [{'policy': 'new_policy'}]
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_cluster = rsrc_defns['senlin-cluster']
        self.senlin_mock.cluster_detach_policy.return_value = {
            'action': 'fake-action'}
        self.senlin_mock.cluster_attach_policy.return_value = {
            'action': 'fake-action'}
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='SUCCEEDED')
        scheduler.TaskRunner(cluster.update, new_cluster)()
        self.assertEqual((cluster.UPDATE, cluster.COMPLETE), cluster.state)
        detach_policy_kwargs = {
            'policy': 'fake_policy_id',
            'cluster': cluster.resource_id,
            'enabled': True,
        }
        self.assertEqual(2,
                         self.senlin_mock.cluster_attach_policy.call_count)
        self.senlin_mock.cluster_detach_policy.assert_called_once_with(
            **detach_policy_kwargs)
        self.assertEqual(0, self.senlin_mock.cluster_update_policy.call_count)
        self.assertEqual(4, self.senlin_mock.get_action.call_count)

    def test_cluster_update_policy_exists(self):
        cluster = self._create_cluster(self.t)
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-cluster']['properties']
        props['policies'] = [{'policy': 'fake_policy', 'enabled': False}]
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_cluster = rsrc_defns['senlin-cluster']
        self.senlin_mock.cluster_update_policy.return_value = {
            'action': 'fake-action'}
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='SUCCEEDED')
        scheduler.TaskRunner(cluster.update, new_cluster)()
        self.assertEqual((cluster.UPDATE, cluster.COMPLETE), cluster.state)
        update_policy_kwargs = {
            'policy': 'fake_policy_id',
            'cluster': cluster.resource_id,
            'enabled': False,
        }
        self.senlin_mock.cluster_update_policy.assert_called_once_with(
            **update_policy_kwargs)
        self.assertEqual(1, self.senlin_mock.cluster_attach_policy.call_count)
        self.assertEqual(0, self.senlin_mock.cluster_detach_policy.call_count)

    def test_cluster_update_failed(self):
        cluster = self._create_cluster(self.t)
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-cluster']['properties']
        props['desired_capacity'] = 3
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        update_snippet = rsrc_defns['senlin-cluster']
        self.senlin_mock.cluster_resize.return_value = {
            'action': 'fake-action'}
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='FAILED', status_reason='Unknown')
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(cluster.update, update_snippet))
        self.assertEqual('ResourceInError: resources.senlin-cluster: '
                         'Went to status FAILED due to "Unknown"',
                         six.text_type(exc))

    def test_cluster_get_attr_collect(self):
        cluster = self._create_cluster(self.t)
        self.senlin_mock.collect_cluster_attrs.return_value = [
            mock.Mock(attr_value='ip1')]
        attr_path1 = ['details.addresses.private[0].addr']
        self.assertEqual(
            ['ip1'], cluster.get_attribute(cluster.ATTR_COLLECT, *attr_path1))
        attr_path2 = ['details.addresses.private[0].addr', 0]
        self.assertEqual(
            'ip1', cluster.get_attribute(cluster.ATTR_COLLECT, *attr_path2))
        self.senlin_mock.collect_cluster_attrs.assert_called_with(
            cluster.resource_id, attr_path2[0])

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
            'nodes': ['node1'],
            'profile_name': 'fake_profile',
            'profile_id': 'fake_profile_id',
            'policies': [{'policy_id': 'fake_policy_id', 'enabled': True}]
        }
        cluster = self._create_cluster(self.t)
        self.assertEqual(self.fake_cl.desired_capacity,
                         cluster._resolve_attribute('desired_capacity'))
        self.assertEqual(['node1'],
                         cluster._resolve_attribute('nodes'))
        self.assertEqual(excepted_show,
                         cluster._show_resource())

    def test_cluster_get_live_state(self):
        expected_reality = {
            'name': 'SenlinCluster',
            'metadata': {'foo': 'bar'},
            'timeout': 3600,
            'desired_capacity': 1,
            'max_size': -1,
            'min_size': 0,
            'profile': 'fake_profile_id',
            'policies': [{'policy': 'fake_policy_id', 'enabled': True}]
        }
        cluster = self._create_cluster(self.t)
        self.senlin_mock.get_cluster.return_value = self.fake_cl

        reality = cluster.get_live_state(cluster.properties)

        self.assertEqual(expected_reality, reality)


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
