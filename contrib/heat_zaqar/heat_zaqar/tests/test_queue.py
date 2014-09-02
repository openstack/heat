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

import six

from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import utils

from ..resources import queue  # noqa

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
      "Value": { "Fn::GetAtt" : [ "MyQueue2", "queue_id" ]},
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

    def exists(self):
        return self._exists

    def ensure_exists(self):
        self._exists = True

    def metadata(self, new_meta=None):
        pass

    def delete(self):
        pass


class ZaqarMessageQueueTest(HeatTestCase):
    def setUp(self):
        super(ZaqarMessageQueueTest, self).setUp()
        self.fc = self.m.CreateMockAnything()
        self.ctx = utils.dummy_context()
        resource._register_class("OS::Zaqar::Queue",
                                 queue.ZaqarQueue)

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        self.stack = parser.Stack(self.ctx, stack_name, tmpl)
        self.stack.validate()
        self.stack.store()

    def test_create(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        self.m.StubOutWithMock(queue, 'zaqar')
        queue.zaqar().MultipleTimes().AndReturn(self.fc)

        fake_q = FakeQueue(queue.physical_resource_name(), auto_create=False)
        self.m.StubOutWithMock(self.fc, 'queue')
        self.fc.queue(queue.physical_resource_name(),
                      auto_create=False).AndReturn(fake_q)
        self.m.StubOutWithMock(fake_q, 'exists')
        fake_q.exists().AndReturn(False)
        self.m.StubOutWithMock(fake_q, 'ensure_exists')
        fake_q.ensure_exists()
        fake_q.exists().AndReturn(True)
        self.m.StubOutWithMock(fake_q, 'metadata')
        fake_q.metadata(new_meta=queue.properties.get('metadata'))

        self.m.ReplayAll()

        scheduler.TaskRunner(queue.create)()
        self.fc.api_url = 'http://127.0.0.1:8888/v1'
        self.assertEqual('myqueue', queue.FnGetAtt('queue_id'))
        self.assertEqual('http://127.0.0.1:8888/v1/queues/myqueue',
                         queue.FnGetAtt('href'))

        self.m.VerifyAll()

    def test_create_existing_queue(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        self.m.StubOutWithMock(queue, 'zaqar')
        queue.zaqar().MultipleTimes().AndReturn(self.fc)

        fake_q = FakeQueue("myqueue", auto_create=False)
        self.m.StubOutWithMock(self.fc, 'queue')
        self.fc.queue("myqueue", auto_create=False).AndReturn(fake_q)
        self.m.StubOutWithMock(fake_q, 'exists')
        fake_q.exists().AndReturn(True)
        self.m.ReplayAll()

        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(queue.create))
        self.assertEqual("Error: Message queue myqueue already exists.",
                         six.text_type(err))
        self.m.VerifyAll()

    def test_create_failed(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        self.m.StubOutWithMock(queue, 'zaqar')
        queue.zaqar().MultipleTimes().AndReturn(self.fc)

        fake_q = FakeQueue("myqueue", auto_create=False)
        self.m.StubOutWithMock(self.fc, 'queue')
        self.fc.queue("myqueue", auto_create=False).AndReturn(fake_q)
        self.m.StubOutWithMock(fake_q, 'exists')
        fake_q.exists().AndReturn(False)
        self.m.StubOutWithMock(fake_q, 'ensure_exists')
        fake_q.ensure_exists()
        fake_q.exists().AndReturn(False)

        self.m.ReplayAll()

        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(queue.create))
        self.assertEqual("Error: Message queue myqueue creation failed.",
                         six.text_type(err))
        self.m.VerifyAll()

    def test_delete(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))
        self.m.StubOutWithMock(queue, 'zaqar')
        queue.zaqar().MultipleTimes().AndReturn(self.fc)

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

    def test_update_in_place(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)
        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))
        self.m.StubOutWithMock(queue, 'zaqar')
        queue.zaqar().MultipleTimes().AndReturn(self.fc)
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
        self.m.StubOutWithMock(queue, 'zaqar')
        queue.zaqar().MultipleTimes().AndReturn(self.fc)
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
        err = self.assertRaises(resource.UpdateReplace,
                                scheduler.TaskRunner(queue.update,
                                                     new_queue))
        msg = 'The Resource MyQueue2 requires replacement.'
        self.assertEqual(msg, six.text_type(err))

        self.m.VerifyAll()
