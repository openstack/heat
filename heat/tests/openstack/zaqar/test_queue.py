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

from six.moves.urllib import parse as urlparse

from heat.common import template_format
from heat.engine.clients import client_plugin
from heat.engine import resource
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
        self._metadata = None
        self._delete_called = False
        self.metadata = mock.Mock()
        self.delete = mock.Mock()


class FakeClient(object):
    def __init__(self):
        self.api_url = 'http://127.0.0.1:8888/'
        self.api_version = 1.1
        self.queue = mock.Mock()


class ZaqarMessageQueueTest(common.HeatTestCase):
    def setUp(self):
        super(ZaqarMessageQueueTest, self).setUp()
        self.fc = FakeClient()
        self.patchobject(resource.Resource, 'client', return_value=self.fc)
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
        queue_metadata = queue.properties.get('metadata')
        fake_q = FakeQueue(queue.physical_resource_name(), auto_create=False)
        fake_q.metadata.return_value = queue_metadata
        self.fc.queue.return_value = fake_q

        scheduler.TaskRunner(queue.create)()
        self.assertEqual('http://127.0.0.1:8888/v1.1/queues/myqueue',
                         queue.FnGetAtt('href'))
        self.fc.queue.assert_called_once_with(queue.physical_resource_name(),
                                              auto_create=False)
        fake_q.metadata.assert_called_once_with(new_meta=queue_metadata)

    def test_create_default_name(self):
        t = template_format.parse(wp_template)
        del t['Resources']['MyQueue2']['Properties']['name']
        self.parse_stack(t)

        queue = self.stack['MyQueue2']

        name_match = utils.PhysName(self.stack.name, 'MyQueue2')
        self.fc.queue.side_effect = FakeQueue
        scheduler.TaskRunner(queue.create)()
        queue_name = queue.physical_resource_name()
        self.assertEqual(name_match, queue_name)

        self.fc.api_version = 2
        self.assertEqual('http://127.0.0.1:8888/v2/queues/' + queue_name,
                         queue.FnGetAtt('href'))
        self.fc.queue.assert_called_once_with(name_match, auto_create=False)

    def test_delete(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))

        fake_q = FakeQueue("myqueue", auto_create=False)
        self.fc.queue.return_value = fake_q

        scheduler.TaskRunner(queue.create)()
        self.fc.queue.assert_called_once_with("myqueue", auto_create=False)
        scheduler.TaskRunner(queue.delete)()
        fake_q.delete.assert_called()

    @mock.patch.object(queue.ZaqarQueue, "client")
    def test_delete_not_found(self, mockclient):
        class ZaqarClientPlugin(client_plugin.ClientPlugin):
            def _create(self):
                return mockclient()

        mock_def = mock.Mock(spec=rsrc_defn.ResourceDefinition)
        mock_def.resource_type = 'OS::Zaqar::Queue'
        props = mock.Mock()
        props.props = {}
        mock_def.properties.return_value = props
        stack = utils.parse_stack(template_format.parse(wp_template))
        self.patchobject(stack, 'db_resource_get', return_value=None)
        mockplugin = ZaqarClientPlugin(self.ctx)
        clients = self.patchobject(stack, 'clients')
        clients.client_plugin.return_value = mockplugin

        mockplugin.is_not_found = mock.Mock()
        mockplugin.is_not_found.return_value = True

        zaqar_q = mock.Mock()
        zaqar_q.delete.side_effect = ResourceNotFound()
        mockclient.return_value.queue.return_value = zaqar_q
        zplugin = queue.ZaqarQueue("test_delete_not_found", mock_def,
                                   stack)
        zplugin.resource_id = "test_delete_not_found"
        zplugin.handle_delete()
        clients.client_plugin.assert_called_once_with('zaqar')
        mockplugin.is_not_found.assert_called_once_with(
            zaqar_q.delete.side_effect)
        mockclient.return_value.queue.assert_called_once_with(
            "test_delete_not_found", auto_create=False)

    def test_update_in_place(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)
        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))
        fake_q = FakeQueue('myqueue', auto_create=False)
        self.fc.queue.return_value = fake_q
        t = template_format.parse(wp_template)
        new_queue = t['Resources']['MyQueue2']
        new_queue['Properties']['metadata'] = {'key1': 'value'}
        resource_defns = template.Template(t).resource_definitions(self.stack)

        scheduler.TaskRunner(queue.create)()
        self.fc.queue.assert_called_once_with("myqueue", auto_create=False)
        fake_q.metadata.assert_called_with(new_meta={'key1': {'key2': 'value',
                                                              'key3': [1, 2]}})

        scheduler.TaskRunner(queue.update, resource_defns['MyQueue2'])()
        fake_q.metadata.assert_called_with(
            new_meta={'key1': 'value'})

    def test_update_replace(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)
        queue = self.stack['MyQueue2']
        queue.resource_id_set(queue.properties.get('name'))
        fake_q = FakeQueue('myqueue', auto_create=False)
        self.fc.queue.return_value = fake_q

        t = template_format.parse(wp_template)
        t['Resources']['MyQueue2']['Properties']['name'] = 'new_queue'
        resource_defns = template.Template(t).resource_definitions(self.stack)
        new_queue = resource_defns['MyQueue2']

        scheduler.TaskRunner(queue.create)()
        self.fc.queue.assert_called_once_with("myqueue", auto_create=False)
        err = self.assertRaises(resource.UpdateReplace,
                                scheduler.TaskRunner(queue.update,
                                                     new_queue))
        msg = 'The Resource MyQueue2 requires replacement.'
        self.assertEqual(msg, six.text_type(err))

    def test_show_resource(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        fake_q = FakeQueue(queue.physical_resource_name(), auto_create=False)
        queue_metadata = queue.properties.get('metadata')
        fake_q.metadata.return_value = queue_metadata
        self.fc.queue.return_value = fake_q

        scheduler.TaskRunner(queue.create)()
        self.fc.queue.assert_called_once_with(queue.physical_resource_name(),
                                              auto_create=False)
        self.assertEqual(
            {'metadata': {"key1": {"key2": "value", "key3": [1, 2]}}},
            queue._show_resource())
        fake_q.metadata.assert_called_with()

    def test_parse_live_resource_data(self):
        t = template_format.parse(wp_template)
        self.parse_stack(t)

        queue = self.stack['MyQueue2']
        fake_q = FakeQueue(queue.physical_resource_name(), auto_create=False)
        self.fc.queue.return_value = fake_q
        queue_metadata = queue.properties.get('metadata')
        fake_q.metadata.return_value = queue_metadata
        scheduler.TaskRunner(queue.create)()
        fake_q.metadata.assert_called_with(new_meta=queue_metadata)
        self.fc.queue.assert_called_once_with(queue.physical_resource_name(),
                                              auto_create=False)
        self.assertEqual(
            {'metadata': {"key1": {"key2": "value", "key3": [1, 2]}},
             'name': queue.resource_id},
            queue.parse_live_resource_data(queue.properties,
                                           queue._show_resource()))
        fake_q.metadata.assert_called_with()


class ZaqarSignedQueueURLTest(common.HeatTestCase):
    tmpl = '''
heat_template_version: 2015-10-15
resources:
  signed_url:
    type: OS::Zaqar::SignedQueueURL
    properties:
      queue: foo
      ttl: 60
      paths:
        - messages
        - subscription
      methods:
        - POST
        - DELETE
'''

    @mock.patch('zaqarclient.queues.v2.queues.Queue.signed_url')
    def test_create(self, mock_signed_url):
        mock_signed_url.return_value = {
            'expires': '2020-01-01',
            'signature': 'secret',
            'project': 'project_id',
            'paths': ['/v2/foo/messages', '/v2/foo/sub'],
            'methods': ['DELETE', 'POST']}

        self.t = template_format.parse(self.tmpl)
        self.stack = utils.parse_stack(self.t)
        self.rsrc = self.stack['signed_url']
        self.assertIsNone(self.rsrc.validate())
        self.stack.create()
        self.assertEqual(self.rsrc.CREATE, self.rsrc.action)
        self.assertEqual(self.rsrc.COMPLETE, self.rsrc.status)
        self.assertEqual(self.stack.CREATE, self.stack.action)
        self.assertEqual(self.stack.COMPLETE, self.stack.status)

        mock_signed_url.assert_called_once_with(
            paths=['messages', 'subscription'],
            methods=['POST', 'DELETE'],
            ttl_seconds=60)

        self.assertEqual('secret', self.rsrc.FnGetAtt('signature'))
        self.assertEqual('2020-01-01', self.rsrc.FnGetAtt('expires'))
        self.assertEqual('project_id', self.rsrc.FnGetAtt('project'))
        self.assertEqual(['/v2/foo/messages', '/v2/foo/sub'],
                         self.rsrc.FnGetAtt('paths'))
        self.assertEqual(['DELETE', 'POST'], self.rsrc.FnGetAtt('methods'))
        expected_query = {
            'queue_name': ['foo'],
            'expires': ['2020-01-01'],
            'signature': ['secret'],
            'project_id': ['project_id'],
            'paths': ['/v2/foo/messages,/v2/foo/sub'],
            'methods': ['DELETE,POST']
        }
        query_str_attr = self.rsrc.get_attribute('query_str')
        self.assertEqual(expected_query,
                         urlparse.parse_qs(query_str_attr,
                                           strict_parsing=True))
