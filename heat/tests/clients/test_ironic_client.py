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

from unittest import mock

from ironicclient import exceptions as ic_exc

from heat.engine.clients.os import ironic as ic
from heat.tests import common
from heat.tests import utils


class IronicClientPluginTest(common.HeatTestCase):

    def test_create(self):
        context = utils.dummy_context()
        plugin = context.clients.client_plugin('ironic')
        client = plugin.client()
        self.assertEqual('http://server.test:5000/v3',
                         client.port.api.session.auth.endpoint)


class fake_resource(object):
    def __init__(self, id=None, name=None):
        self.uuid = id
        self.name = name


class PortGroupConstraintTest(common.HeatTestCase):
    def setUp(self):
        super(PortGroupConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_port_group_get = mock.Mock()
        self.ctx.clients.client_plugin(
            'ironic').client().portgroup.get = self.mock_port_group_get
        self.constraint = ic.PortGroupConstraint()

    def test_validate(self):
        self.mock_port_group_get.return_value = fake_resource(
            id='my_port_group')
        self.assertTrue(self.constraint.validate(
            'my_port_group', self.ctx))

    def test_validate_fail(self):
        self.mock_port_group_get.side_effect = ic_exc.NotFound()
        self.assertFalse(self.constraint.validate(
            "bad_port_group", self.ctx))


class NodeConstraintTest(common.HeatTestCase):
    def setUp(self):
        super(NodeConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_node_get = mock.Mock()
        self.ctx.clients.client_plugin(
            'ironic').client().node.get = self.mock_node_get
        self.constraint = ic.NodeConstraint()

    def test_validate(self):
        self.mock_node_get.return_value = fake_resource(
            id='my_node')
        self.assertTrue(self.constraint.validate(
            'my_node', self.ctx))

    def test_validate_fail(self):
        self.mock_node_get.side_effect = ic_exc.NotFound()
        self.assertFalse(self.constraint.validate(
            "bad_node", self.ctx))
