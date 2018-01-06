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
from heat.engine.resources.openstack.senlin import node as sn
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils
from openstack import exceptions


node_stack_template = """
heat_template_version: 2016-04-08
description: Senlin Node Template
resources:
  senlin-node:
    type: OS::Senlin::Node
    properties:
      name: SenlinNode
      profile: fake_profile
      cluster: fake_cluster
      metadata:
        foo: bar
"""


class FakeNode(object):
    def __init__(self, id='some_id', status='ACTIVE'):
        self.status = status
        self.status_reason = 'Unknown'
        self.id = id
        self.name = "SenlinNode"
        self.metadata = {'foo': 'bar'}
        self.profile_id = "fake_profile_id"
        self.cluster_id = "fake_cluster_id"
        self.details = {'id': 'physical_object_id'}
        self.location = "actions/fake_action"

    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'status_reason': self.status_reason,
            'name': self.name,
            'metadata': self.metadata,
            'profile_id': self.profile_id,
            'cluster_id': self.cluster_id,
        }


class SenlinNodeTest(common.HeatTestCase):
    def setUp(self):
        super(SenlinNodeTest, self).setUp()
        self.senlin_mock = mock.MagicMock()
        self.senlin_mock.get_profile.return_value = mock.Mock(
            id='fake_profile_id'
        )
        self.senlin_mock.get_cluster.return_value = mock.Mock(
            id='fake_cluster_id'
        )
        self.patchobject(sn.Node, 'client', return_value=self.senlin_mock)
        self.patchobject(senlin.SenlinClientPlugin, 'client',
                         return_value=self.senlin_mock)
        self.patchobject(senlin.ProfileConstraint, 'validate',
                         return_value=True)
        self.patchobject(senlin.ClusterConstraint, 'validate',
                         return_value=True)
        self.fake_node = FakeNode()
        self.t = template_format.parse(node_stack_template)
        self.stack = utils.parse_stack(self.t)
        self.node = self.stack['senlin-node']

    def _create_node(self):
        self.senlin_mock.create_node.return_value = self.fake_node
        self.senlin_mock.get_node.return_value = self.fake_node
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='SUCCEEDED')
        scheduler.TaskRunner(self.node.create)()
        self.assertEqual((self.node.CREATE, self.node.COMPLETE),
                         self.node.state)
        self.assertEqual(self.fake_node.id, self.node.resource_id)
        return self.node

    def test_node_create_success(self):
        self._create_node()
        expect_kwargs = {
            'name': 'SenlinNode',
            'profile_id': 'fake_profile_id',
            'metadata': {'foo': 'bar'},
            'cluster_id': 'fake_cluster_id',
        }
        self.senlin_mock.create_node.assert_called_once_with(
            **expect_kwargs)

    def test_node_create_error(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        self.senlin_mock.create_node.return_value = self.fake_node
        mock_action = mock.MagicMock()
        mock_action.status = 'FAILED'
        mock_action.status_reason = 'oops'
        self.senlin_mock.get_action.return_value = mock_action
        create_task = scheduler.TaskRunner(self.node.create)
        ex = self.assertRaises(exception.ResourceFailure, create_task)
        expected = ('ResourceInError: resources.senlin-node: '
                    'Went to status FAILED due to "oops"')
        self.assertEqual(expected, six.text_type(ex))

    def test_node_delete_success(self):
        node = self._create_node()
        self.senlin_mock.get_node.side_effect = [
            exceptions.ResourceNotFound('SenlinNode'),
        ]
        scheduler.TaskRunner(node.delete)()
        self.senlin_mock.delete_node.assert_called_once_with(
            node.resource_id)

    def test_cluster_delete_error(self):
        node = self._create_node()
        self.senlin_mock.get_node.side_effect = exception.Error('oops')
        delete_task = scheduler.TaskRunner(node.delete)
        ex = self.assertRaises(exception.ResourceFailure, delete_task)
        expected = 'Error: resources.senlin-node: oops'
        self.assertEqual(expected, six.text_type(ex))

    def test_node_update_profile(self):
        node = self._create_node()
        # Mock translate rules
        self.senlin_mock.get_profile.side_effect = [
            mock.Mock(id='new_profile_id'),
            mock.Mock(id='fake_profile_id'),
            mock.Mock(id='new_profile_id'),
        ]
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-node']['properties']
        props['profile'] = 'new_profile'
        props['name'] = 'new_name'
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_node = rsrc_defns['senlin-node']
        self.senlin_mock.update_node.return_value = mock.Mock(
            location='/actions/fake-action')
        scheduler.TaskRunner(node.update, new_node)()
        self.assertEqual((node.UPDATE, node.COMPLETE), node.state)
        node_update_kwargs = {
            'profile_id': 'new_profile_id',
            'name': 'new_name'
        }
        self.senlin_mock.update_node.assert_called_once_with(
            node=self.fake_node, **node_update_kwargs)
        self.assertEqual(2, self.senlin_mock.get_action.call_count)

    def test_node_update_cluster(self):
        node = self._create_node()
        # Mock translate rules
        self.senlin_mock.get_cluster.side_effect = [
            mock.Mock(id='new_cluster_id'),
            mock.Mock(id='fake_cluster_id'),
            mock.Mock(id='new_cluster_id'),
        ]
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-node']['properties']
        props['cluster'] = 'new_cluster'
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_node = rsrc_defns['senlin-node']
        self.senlin_mock.cluster_del_nodes.return_value = {
            'action': 'remove_node_from_cluster'
        }
        self.senlin_mock.cluster_add_nodes.return_value = {
            'action': 'add_node_to_cluster'
        }
        scheduler.TaskRunner(node.update, new_node)()
        self.assertEqual((node.UPDATE, node.COMPLETE), node.state)
        self.senlin_mock.cluster_del_nodes.assert_called_once_with(
            cluster='fake_cluster_id', nodes=[node.resource_id])
        self.senlin_mock.cluster_add_nodes.assert_called_once_with(
            cluster='new_cluster_id', nodes=[node.resource_id])

    def test_node_update_failed(self):
        node = self._create_node()
        new_t = copy.deepcopy(self.t)
        props = new_t['resources']['senlin-node']['properties']
        props['name'] = 'new_name'
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_node = rsrc_defns['senlin-node']
        self.senlin_mock.update_node.return_value = mock.Mock(
            location='/actions/fake-action')
        self.senlin_mock.get_action.return_value = mock.Mock(
            status='FAILED', status_reason='oops')
        update_task = scheduler.TaskRunner(node.update, new_node)
        ex = self.assertRaises(exception.ResourceFailure, update_task)
        expected = ('ResourceInError: resources.senlin-node: Went to '
                    'status FAILED due to "oops"')
        self.assertEqual(expected, six.text_type(ex))
        self.assertEqual((node.UPDATE, node.FAILED), node.state)
        self.assertEqual(2, self.senlin_mock.get_action.call_count)

    def test_cluster_resolve_attribute(self):
        excepted_show = {
            'id': 'some_id',
            'status': 'ACTIVE',
            'status_reason': 'Unknown',
            'name': 'SenlinNode',
            'metadata': {'foo': 'bar'},
            'profile_id': 'fake_profile_id',
            'cluster_id': 'fake_cluster_id'
        }
        node = self._create_node()
        self.assertEqual(excepted_show,
                         node._show_resource())
        self.assertEqual(self.fake_node.details,
                         node._resolve_attribute('details'))
        self.senlin_mock.get_node.assert_called_with(
            node.resource_id, details=True)

    def test_node_get_live_state(self):
        expected_reality = {
            'name': 'SenlinNode',
            'metadata': {'foo': 'bar'},
            'profile': 'fake_profile_id',
            'cluster': 'fake_cluster_id'
        }
        node = self._create_node()
        reality = node.get_live_state(node.properties)
        self.assertEqual(expected_reality, reality)
