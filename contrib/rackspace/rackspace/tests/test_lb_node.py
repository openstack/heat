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

import datetime

import mock

from heat.engine import rsrc_defn
from heat.tests import common

from ..resources import lb_node  # noqa
from ..resources.lb_node import (  # noqa
    LoadbalancerDeleted,
    NotFound,
    NodeNotFound)

from .test_cloud_loadbalancer import FakeNode  # noqa


class LBNode(lb_node.LBNode):
    @classmethod
    def is_service_available(cls, context):
        return True


class LBNodeTest(common.HeatTestCase):
    def setUp(self):
        super(LBNodeTest, self).setUp()
        self.mockstack = mock.Mock()
        self.mockstack.has_cache_data.return_value = False
        self.mockstack.db_resource_get.return_value = None
        self.mockclient = mock.Mock()
        self.mockstack.clients.client.return_value = self.mockclient

        self.def_props = {
            LBNode.LOAD_BALANCER: 'some_lb_id',
            LBNode.DRAINING_TIMEOUT: 60,
            LBNode.ADDRESS: 'some_ip',
            LBNode.PORT: 80,
            LBNode.CONDITION: 'ENABLED',
            LBNode.TYPE: 'PRIMARY',
            LBNode.WEIGHT: None,
        }
        self.resource_def = rsrc_defn.ResourceDefinition(
            "test", LBNode, properties=self.def_props)

        self.resource = LBNode("test", self.resource_def, self.mockstack)
        self.resource.resource_id = 12345

    def test_create(self):
        self.resource.resource_id = None

        fake_lb = mock.Mock()
        fake_lb.add_nodes.return_value = (None, {'nodes': [{'id': 12345}]})
        self.mockclient.get.return_value = fake_lb

        fake_node = mock.Mock()
        self.mockclient.Node.return_value = fake_node

        self.resource.check_create_complete()

        self.mockclient.get.assert_called_once_with('some_lb_id')
        self.mockclient.Node.assert_called_once_with(
            address='some_ip', port=80, condition='ENABLED',
            type='PRIMARY', weight=0)
        fake_lb.add_nodes.assert_called_once_with([fake_node])
        self.assertEqual(self.resource.resource_id, 12345)

    def test_create_lb_not_found(self):
        self.mockclient.get.side_effect = NotFound()
        self.assertRaises(NotFound, self.resource.check_create_complete)

    def test_create_lb_deleted(self):
        fake_lb = mock.Mock()
        fake_lb.id = 1111
        fake_lb.status = 'DELETED'
        self.mockclient.get.return_value = fake_lb

        exc = self.assertRaises(LoadbalancerDeleted,
                                self.resource.check_create_complete)
        self.assertEqual("The Load Balancer (ID 1111) has been deleted.",
                         str(exc))

    def test_create_lb_pending_delete(self):
        fake_lb = mock.Mock()
        fake_lb.id = 1111
        fake_lb.status = 'PENDING_DELETE'
        self.mockclient.get.return_value = fake_lb

        exc = self.assertRaises(LoadbalancerDeleted,
                                self.resource.check_create_complete)
        self.assertEqual("The Load Balancer (ID 1111) has been deleted.",
                         str(exc))

    def test_handle_update_method(self):
        self.assertEqual(self.resource.handle_update(None, None, 'foo'), 'foo')

    def _test_update(self, diff):
        fake_lb = mock.Mock()
        fake_node = FakeNode(id=12345, address='a', port='b')
        fake_node.update = mock.Mock()
        expected_node = FakeNode(id=12345, address='a', port='b', **diff)
        expected_node.update = fake_node.update
        fake_lb.nodes = [fake_node]
        self.mockclient.get.return_value = fake_lb

        self.assertFalse(self.resource.check_update_complete(prop_diff=diff))

        self.mockclient.get.assert_called_once_with('some_lb_id')
        fake_node.update.assert_called_once_with()
        self.assertEqual(fake_node, expected_node)

    def test_update_condition(self):
        self._test_update({'condition': 'DISABLED'})

    def test_update_weight(self):
        self._test_update({'weight': 100})

    def test_update_type(self):
        self._test_update({'type': 'SECONDARY'})

    def test_update_multiple(self):
        self._test_update({'condition': 'DISABLED',
                           'weight': 100,
                           'type': 'SECONDARY'})

    def test_update_finished(self):
        fake_lb = mock.Mock()
        fake_node = FakeNode(id=12345, address='a', port='b',
                             condition='ENABLED')
        fake_node.update = mock.Mock()
        expected_node = FakeNode(id=12345, address='a', port='b',
                                 condition='ENABLED')
        expected_node.update = fake_node.update
        fake_lb.nodes = [fake_node]
        self.mockclient.get.return_value = fake_lb

        diff = {'condition': 'ENABLED'}
        self.assertTrue(self.resource.check_update_complete(prop_diff=diff))

        self.mockclient.get.assert_called_once_with('some_lb_id')
        self.assertFalse(fake_node.update.called)
        self.assertEqual(fake_node, expected_node)

    def test_update_lb_not_found(self):
        self.mockclient.get.side_effect = NotFound()

        diff = {'condition': 'ENABLED'}
        self.assertRaises(NotFound, self.resource.check_update_complete,
                          prop_diff=diff)

    def test_update_lb_deleted(self):
        fake_lb = mock.Mock()
        fake_lb.id = 1111
        fake_lb.status = 'DELETED'
        self.mockclient.get.return_value = fake_lb

        diff = {'condition': 'ENABLED'}
        exc = self.assertRaises(LoadbalancerDeleted,
                                self.resource.check_update_complete,
                                prop_diff=diff)
        self.assertEqual("The Load Balancer (ID 1111) has been deleted.",
                         str(exc))

    def test_update_lb_pending_delete(self):
        fake_lb = mock.Mock()
        fake_lb.id = 1111
        fake_lb.status = 'PENDING_DELETE'
        self.mockclient.get.return_value = fake_lb

        diff = {'condition': 'ENABLED'}
        exc = self.assertRaises(LoadbalancerDeleted,
                                self.resource.check_update_complete,
                                prop_diff=diff)
        self.assertEqual("The Load Balancer (ID 1111) has been deleted.",
                         str(exc))

    def test_update_node_not_found(self):
        fake_lb = mock.Mock()
        fake_lb.id = 4444
        fake_lb.nodes = []
        self.mockclient.get.return_value = fake_lb

        diff = {'condition': 'ENABLED'}
        exc = self.assertRaises(NodeNotFound,
                                self.resource.check_update_complete,
                                prop_diff=diff)
        self.assertEqual(
            "Node (ID 12345) not found on Load Balancer (ID 4444).", str(exc))

    def test_delete_no_id(self):
        self.resource.resource_id = None
        self.assertTrue(self.resource.check_delete_complete(None))

    def test_delete_lb_already_deleted(self):
        self.mockclient.get.side_effect = NotFound()
        self.assertTrue(self.resource.check_delete_complete(None))
        self.mockclient.get.assert_called_once_with('some_lb_id')

    def test_delete_lb_deleted_status(self):
        fake_lb = mock.Mock()
        fake_lb.status = 'DELETED'
        self.mockclient.get.return_value = fake_lb

        self.assertTrue(self.resource.check_delete_complete(None))
        self.mockclient.get.assert_called_once_with('some_lb_id')

    def test_delete_lb_pending_delete_status(self):
        fake_lb = mock.Mock()
        fake_lb.status = 'PENDING_DELETE'
        self.mockclient.get.return_value = fake_lb

        self.assertTrue(self.resource.check_delete_complete(None))
        self.mockclient.get.assert_called_once_with('some_lb_id')

    def test_delete_node_already_deleted(self):
        fake_lb = mock.Mock()
        fake_lb.nodes = []
        self.mockclient.get.return_value = fake_lb

        self.assertTrue(self.resource.check_delete_complete(None))
        self.mockclient.get.assert_called_once_with('some_lb_id')

    @mock.patch.object(lb_node.timeutils, 'utcnow')
    def test_drain_before_delete(self, mock_utcnow):
        fake_lb = mock.Mock()
        fake_node = FakeNode(id=12345, address='a', port='b')
        expected_node = FakeNode(id=12345, address='a', port='b',
                                 condition='DRAINING')
        fake_node.update = mock.Mock()
        expected_node.update = fake_node.update
        fake_node.delete = mock.Mock()
        expected_node.delete = fake_node.delete
        fake_lb.nodes = [fake_node]
        self.mockclient.get.return_value = fake_lb

        now = datetime.datetime.utcnow()
        mock_utcnow.return_value = now

        self.assertFalse(self.resource.check_delete_complete(now))

        self.mockclient.get.assert_called_once_with('some_lb_id')
        fake_node.update.assert_called_once_with()
        self.assertFalse(fake_node.delete.called)
        self.assertEqual(fake_node, expected_node)

    @mock.patch.object(lb_node.timeutils, 'utcnow')
    def test_delete_waiting(self, mock_utcnow):
        fake_lb = mock.Mock()
        fake_node = FakeNode(id=12345, address='a', port='b',
                             condition='DRAINING')
        expected_node = FakeNode(id=12345, address='a', port='b',
                                 condition='DRAINING')
        fake_node.update = mock.Mock()
        expected_node.update = fake_node.update
        fake_node.delete = mock.Mock()
        expected_node.delete = fake_node.delete
        fake_lb.nodes = [fake_node]
        self.mockclient.get.return_value = fake_lb

        now = datetime.datetime.utcnow()
        now_plus_30 = now + datetime.timedelta(seconds=30)
        mock_utcnow.return_value = now_plus_30

        self.assertFalse(self.resource.check_delete_complete(now))

        self.mockclient.get.assert_called_once_with('some_lb_id')
        self.assertFalse(fake_node.update.called)
        self.assertFalse(fake_node.delete.called)
        self.assertEqual(fake_node, expected_node)

    @mock.patch.object(lb_node.timeutils, 'utcnow')
    def test_delete_finishing(self, mock_utcnow):
        fake_lb = mock.Mock()
        fake_node = FakeNode(id=12345, address='a', port='b',
                             condition='DRAINING')
        expected_node = FakeNode(id=12345, address='a', port='b',
                                 condition='DRAINING')
        fake_node.update = mock.Mock()
        expected_node.update = fake_node.update
        fake_node.delete = mock.Mock()
        expected_node.delete = fake_node.delete
        fake_lb.nodes = [fake_node]
        self.mockclient.get.return_value = fake_lb

        now = datetime.datetime.utcnow()
        now_plus_62 = now + datetime.timedelta(seconds=62)
        mock_utcnow.return_value = now_plus_62

        self.assertFalse(self.resource.check_delete_complete(now))

        self.mockclient.get.assert_called_once_with('some_lb_id')
        self.assertFalse(fake_node.update.called)
        self.assertTrue(fake_node.delete.called)
        self.assertEqual(fake_node, expected_node)
