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

from openstack import exceptions

from heat.common import template_format
from heat.engine.clients.os import senlin
from heat.engine.resources.openstack.senlin import receiver as sr
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


receiver_stack_template = """
heat_template_version: 2016-04-08
description: Senlin Receiver Template
resources:
  senlin-receiver:
    type: OS::Senlin::Receiver
    properties:
      name: SenlinReceiver
      cluster: fake_cluster
      action: CLUSTER_SCALE_OUT
      type: webhook
      params:
        foo: bar
"""


class FakeReceiver(object):
    def __init__(self, id='some_id'):
        self.id = id
        self.name = "SenlinReceiver"
        self.cluster_id = "fake_cluster"
        self.action = "CLUSTER_SCALE_OUT"
        self.channel = {'alarm_url': "http://foo.bar/webhooks/fake_url"}

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'cluster_id': self.cluster_id,
            'action': self.action,
            'channel': self.channel,
            'actor': {'trust_id': ['fake_trust_id']}
        }


class SenlinReceiverTest(common.HeatTestCase):
    def setUp(self):
        super(SenlinReceiverTest, self).setUp()
        self.senlin_mock = mock.MagicMock()
        self.patchobject(sr.Receiver, 'client',
                         return_value=self.senlin_mock)
        self.patchobject(senlin.ClusterConstraint, 'validate',
                         return_value=True)
        self.fake_r = FakeReceiver()
        self.t = template_format.parse(receiver_stack_template)

    def _init_recv(self, template):
        self.stack = utils.parse_stack(template)
        recv = self.stack['senlin-receiver']
        return recv

    def _create_recv(self, template):
        recv = self._init_recv(template)
        self.senlin_mock.create_receiver.return_value = self.fake_r
        self.senlin_mock.get_receiver.return_value = self.fake_r
        scheduler.TaskRunner(recv.create)()
        self.assertEqual((recv.CREATE, recv.COMPLETE),
                         recv.state)
        self.assertEqual(self.fake_r.id, recv.resource_id)
        return recv

    def test_recv_create_success(self):
        self._create_recv(self.t)
        expect_kwargs = {
            'name': 'SenlinReceiver',
            'cluster_id': 'fake_cluster',
            'action': 'CLUSTER_SCALE_OUT',
            'type': 'webhook',
            'params': {'foo': 'bar'},
        }
        self.senlin_mock.create_receiver.assert_called_once_with(
            **expect_kwargs)

    def test_recv_delete_success(self):
        self.senlin_mock.delete_receiver.return_value = None
        recv = self._create_recv(self.t)
        scheduler.TaskRunner(recv.delete)()
        self.senlin_mock.delete_receiver.assert_called_once_with(
            recv.resource_id)

    def test_recv_delete_not_found(self):
        self.senlin_mock.delete_receiver.side_effect = [
            exceptions.ResourceNotFound(http_status=404)
        ]
        recv = self._create_recv(self.t)
        scheduler.TaskRunner(recv.delete)()
        self.senlin_mock.delete_receiver.assert_called_once_with(
            recv.resource_id)

    def test_cluster_resolve_attribute(self):
        excepted_show = {
            'id': 'some_id',
            'name': 'SenlinReceiver',
            'cluster_id': 'fake_cluster',
            'action': 'CLUSTER_SCALE_OUT',
            'channel': {'alarm_url': "http://foo.bar/webhooks/fake_url"},
            'actor': {'trust_id': ['fake_trust_id']}
        }
        recv = self._create_recv(self.t)
        self.assertEqual(self.fake_r.channel,
                         recv._resolve_attribute('channel'))
        self.assertEqual(excepted_show,
                         recv._show_resource())
