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

import mock
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients import client_plugin
from heat.engine.resources.openstack.zaqar import queue
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

try:
    from zaqarclient.transport.errors import ResourceNotFound  # noqa
except ImportError:
    ResourceNotFound = Exception

wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "openstack Zaqar queue service as a resource",
  "Resources" : {
    "MyQueue2" : {
      "Type" : "OS::Zaqar::Queue",
      "Properties" : {
        "name": "myqueue",
        "metadata": { "key1": { "key2": "value", "key3": [1, 2] } }
      }
    }
  },
  "Outputs" : {
    "queue_id": {
      "Value": { "Ref" : "MyQueue2" },
      "Description": "queue name"
    },
    "queue_href": {
      "Value": { "Fn::GetAtt" : [ "MyQueue2", "href" ]},
      "Description": "queue href"
    }
  }
}
'''


class FakeQueue(object):
    def __init__(self, queue_name, auto_create=True):
        self._id = queue_name
        self._auto_create = auto_create
        self._exists = False

    def metadata(self, new_meta=None):
        pass

    def delete(self):
        pass


class ZaqarMessageQueueTest(common.HeatTestCase):
    def setUp(self):
        super(ZaqarMessageQueueTest, self).setUp()
        self.fc = self.m.CreateMockAnything()
        self.ctx = utils.dummy_context()

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        self.stack = stack.Stack(self.ctx, stack_name, tmpl)
        self.stack.validate()
        self.stack.store()

    def test_create(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        self.m.StubOutWithMock(queue, 'client')
        queue.client().MultipleTimes().AndReturn(self.fc)

        fake_q = FakeQueue(queue.physical_resource_name(), auto_create=False)
        self.m.StubOutWithMock(self.fc, 'queue')
        self.fc.queue(queue.physical_resource_name(),
                      auto_create=False).AndReturn(fake_q)
        self.m.StubOutWithMock(fake_q, 'metadata')
        fake_q.metadata(new_meta=queue.properties.get('metadata'))

        self.m.ReplayAll()

        scheduler.TaskRunner(queue.create)()
        self.fc.api_url = 'http://127.0.0.1:8888/v1'
        self.assertEqual('http://127.0.0.1:8888/v1/queues/myqueue',
                         queue.FnGetAtt('href'))

        self.m.VerifyAll()

    def test_delete(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))
        self.m.StubOutWithMock(queue, 'client')
        queue.client().MultipleTimes().AndReturn(self.fc)

        fake_q = FakeQueue("myqueue", auto_create=False)
        self.m.StubOutWithMock(self.fc, 'queue')
        self.fc.queue("myqueue",
                      auto_create=False).MultipleTimes().AndReturn(fake_q)
        self.m.StubOutWithMock(fake_q, 'delete')
        fake_q.delete()

        self.m.ReplayAll()

        scheduler.TaskRunner(queue.create)()
        scheduler.TaskRunner(queue.delete)()
        self.m.VerifyAll()

    @mock.patch.object(queue.ZaqarQueue, "client")
    def test_delete_not_found(self, mockclient):
        class ZaqarClientPlugin(client_plugin.ClientPlugin):
            def _create(self):
                return mockclient()

        mock_def = mock.Mock(spec=rsrc_defn.ResourceDefinition)
        mock_stack = mock.Mock()
        mock_stack.db_resource_get.return_value = None
        mock_stack.has_cache_data.return_value = False
        mockplugin = ZaqarClientPlugin(self.ctx)
        mock_stack.clients = mock.Mock()
        mock_stack.clients.client_plugin.return_value = mockplugin

        mockplugin.is_not_found = mock.Mock()
        mockplugin.is_not_found.return_value = True

        zaqar_q = mock.Mock()
        zaqar_q.delete.side_effect = ResourceNotFound()
        mockclient.return_value.queue.return_value = zaqar_q
        zplugin = queue.ZaqarQueue("test_delete_not_found", mock_def,
                                   mock_stack)
        zplugin.resource_id = "test_delete_not_found"
        zplugin.handle_delete()
        mock_stack.clients.client_plugin.assert_called_once_with('zaqar')
        mockplugin.is_not_found.assert_called_once_with(
            zaqar_q.delete.side_effect)
        mockclient.return_value.queue.assert_called_once_with(
            "test_delete_not_found", auto_create=False)

    def test_update_in_place(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)
        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))
        self.m.StubOutWithMock(queue, 'client')
        queue.client().MultipleTimes().AndReturn(self.fc)
        fake_q = FakeQueue('myqueue', auto_create=False)
        self.m.StubOutWithMock(self.fc, 'queue')
        self.fc.queue('myqueue',
                      auto_create=False).MultipleTimes().AndReturn(fake_q)
        self.m.StubOutWithMock(fake_q, 'metadata')
        fake_q.metadata(new_meta={"key1": {"key2": "value", "key3": [1, 2]}})

        # Expected to be called during update
        fake_q.metadata(new_meta={'key1': 'value'})

        self.m.ReplayAll()

        t = template_format.parse(wp_template)
        new_queue = t['Resources']['MyQueue2']
        new_queue['Properties']['metadata'] = {'key1': 'value'}
        resource_defns = template.Template(t).resource_definitions(self.stack)

        scheduler.TaskRunner(queue.create)()
        scheduler.TaskRunner(queue.update, resource_defns['MyQueue2'])()
        self.m.VerifyAll()

    def test_update_replace(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)
        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))
        self.m.StubOutWithMock(queue, 'client')
        queue.client().MultipleTimes().AndReturn(self.fc)
        fake_q = FakeQueue('myqueue', auto_create=False)
        self.m.StubOutWithMock(self.fc, 'queue')
        self.fc.queue('myqueue',
                      auto_create=False).MultipleTimes().AndReturn(fake_q)

        self.m.ReplayAll()

        t = template_format.parse(wp_template)
        t['Resources']['MyQueue2']['Properties']['name'] = 'new_queue'
        resource_defns = template.Template(t).resource_definitions(self.stack)
        new_queue = resource_defns['MyQueue2']

        scheduler.TaskRunner(queue.create)()
        err = self.assertRaises(exception.UpdateReplace,
                                scheduler.TaskRunner(queue.update,
                                                     new_queue))
        msg = 'The Resource MyQueue2 requires replacement.'
        self.assertEqual(msg, six.text_type(err))

        self.m.VerifyAll()
