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
from heat.engine.clients.os import mistral as mistral_client_plugin
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils

from oslo_serialization import jsonutils

try:
    from zaqarclient.transport.errors import ResourceNotFound  # noqa
except ImportError:
    class ResourceNotFound(Exception):
        pass

subscr_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Resources" : {
    "MyQueue2" : {
      "Type" : "OS::Zaqar::Queue",
      "Properties" : {
        "name" : "myqueue",
        "metadata" : { "key1" : { "key2" : "value", "key3" : [1, 2] } }
      }
    },
    "MySubscription" : {
      "Type" : "OS::Zaqar::Subscription",
      "Properties" : {
        "queue_name" : "myqueue",
        "subscriber" : "mailto:name@domain.com",
        "ttl" : "3600",
        "options" : { "key1" : "value1" }
      }
    }
  }
}
'''

mistral_template = '''
{
  "heat_template_version" : "2015-10-15",
  "resources" : {
    "subscription" : {
      "type" : "OS::Zaqar::MistralTrigger",
      "properties" : {
        "queue_name" : "myqueue",
        "workflow_id": "abcd",
        "input" : { "key1" : "value1" }
      }
    }
  }
}
'''


class FakeSubscription(object):
    def __init__(self, queue_name, id=None, ttl=None, subscriber=None,
                 options=None, auto_create=True):
        self.id = id
        self.queue_name = queue_name
        self.ttl = ttl
        self.subscriber = subscriber
        self.options = options

    def update(self, prop_diff):
        allowed_keys = {'subscriber', 'ttl', 'options'}
        for key in six.iterkeys(prop_diff):
            if key not in allowed_keys:
                raise KeyError(key)

    def delete(self):
        pass


@mock.patch.object(resource.Resource, "client_plugin")
@mock.patch.object(resource.Resource, "client")
class ZaqarSubscriptionTest(common.HeatTestCase):
    def setUp(self):
        super(ZaqarSubscriptionTest, self).setUp()
        self.fc = self.m.CreateMockAnything()
        self.ctx = utils.dummy_context()

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        self.stack = stack.Stack(self.ctx, stack_name, tmpl)
        self.stack.validate()
        self.stack.store()

    def test_validate_subscriber_type(self, mock_client, mock_plugin):
        t = template_format.parse(subscr_template)
        t['Resources']['MySubscription']['Properties']['subscriber'] = "foo:ba"
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        self.stack = stack.Stack(self.ctx, stack_name, tmpl)

        exc = self.assertRaises(exception.StackValidationFailed,
                                self.stack.validate)
        self.assertEqual('The subscriber type of must be one of: http, https, '
                         'mailto, trust+http, trust+https.',
                         six.text_type(exc))

    def test_create(self, mock_client, mock_plugin):
        t = template_format.parse(subscr_template)
        self.parse_stack(t)

        subscr = self.stack['MySubscription']
        subscr_id = "58138648c1e2eb7355d62137"

        self.m.StubOutWithMock(subscr, 'client')
        subscr.client().MultipleTimes().AndReturn(self.fc)

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options={'key1': 'value1'},
                             subscriber=u'mailto:name@domain.com',
                             ttl=3600).AndReturn(fake_subscr)

        self.m.ReplayAll()

        scheduler.TaskRunner(subscr.create)()
        self.assertEqual(subscr_id, subscr.FnGetRefId())

        self.m.VerifyAll()

    def test_delete(self, mock_client, mock_plugin):
        t = template_format.parse(subscr_template)
        self.parse_stack(t)

        subscr = self.stack['MySubscription']
        subscr_id = "58138648c1e2eb7355d62137"

        self.m.StubOutWithMock(subscr, 'client')
        subscr.client().MultipleTimes().AndReturn(self.fc)

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options={'key1': 'value1'},
                             subscriber=u'mailto:name@domain.com',
                             ttl=3600).AndReturn(fake_subscr)
        self.fc.subscription(subscr.properties['queue_name'],
                             id=subscr_id,
                             auto_create=False).AndReturn(fake_subscr)
        self.m.StubOutWithMock(fake_subscr, 'delete')
        fake_subscr.delete()

        self.m.ReplayAll()

        scheduler.TaskRunner(subscr.create)()
        scheduler.TaskRunner(subscr.delete)()

        self.m.VerifyAll()

    def test_delete_not_found(self, mock_client, mock_plugin):
        t = template_format.parse(subscr_template)
        self.parse_stack(t)

        subscr = self.stack['MySubscription']
        subscr_id = "58138648c1e2eb7355d62137"

        self.m.StubOutWithMock(subscr, 'client')
        subscr.client().MultipleTimes().AndReturn(self.fc)

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options={'key1': 'value1'},
                             subscriber=u'mailto:name@domain.com',
                             ttl=3600).AndReturn(fake_subscr)
        self.fc.subscription(subscr.properties['queue_name'],
                             id=subscr_id,
                             auto_create=False).AndRaise(ResourceNotFound())

        self.m.ReplayAll()

        scheduler.TaskRunner(subscr.create)()
        scheduler.TaskRunner(subscr.delete)()

        self.m.VerifyAll()

    def test_update_in_place(self, mock_client, mock_plugin):
        t = template_format.parse(subscr_template)
        self.parse_stack(t)

        subscr = self.stack['MySubscription']
        subscr_id = "58138648c1e2eb7355d62137"

        self.m.StubOutWithMock(subscr, 'client')
        subscr.client().MultipleTimes().AndReturn(self.fc)

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options={'key1': 'value1'},
                             subscriber=u'mailto:name@domain.com',
                             ttl=3600).AndReturn(fake_subscr)
        self.fc.subscription(subscr.properties['queue_name'],
                             id=subscr_id,
                             auto_create=False).AndReturn(fake_subscr)
        self.m.StubOutWithMock(fake_subscr, 'update')
        fake_subscr.update({'ttl': 3601, 'options': {'key1': 'value1'},
                            'subscriber': 'mailto:name@domain.com'})

        self.m.ReplayAll()

        t = template_format.parse(subscr_template)
        new_subscr = t['Resources']['MySubscription']
        new_subscr['Properties']['ttl'] = "3601"
        resource_defns = template.Template(t).resource_definitions(self.stack)

        scheduler.TaskRunner(subscr.create)()
        scheduler.TaskRunner(subscr.update, resource_defns['MySubscription'])()

        self.m.VerifyAll()

    def test_update_replace(self, mock_client, mock_plugin):
        t = template_format.parse(subscr_template)
        self.parse_stack(t)

        subscr = self.stack['MySubscription']
        subscr_id = "58138648c1e2eb7355d62137"

        self.m.StubOutWithMock(subscr, 'client')
        subscr.client().MultipleTimes().AndReturn(self.fc)

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options={'key1': 'value1'},
                             subscriber=u'mailto:name@domain.com',
                             ttl=3600).AndReturn(fake_subscr)

        self.m.ReplayAll()

        t = template_format.parse(subscr_template)
        t['Resources']['MySubscription']['Properties']['queue_name'] = 'foo'
        resource_defns = template.Template(t).resource_definitions(self.stack)
        new_subscr = resource_defns['MySubscription']

        scheduler.TaskRunner(subscr.create)()
        err = self.assertRaises(resource.UpdateReplace,
                                scheduler.TaskRunner(subscr.update,
                                                     new_subscr))
        msg = 'The Resource MySubscription requires replacement.'
        self.assertEqual(msg, six.text_type(err))

        self.m.VerifyAll()

    def test_show_resource(self, mock_client, mock_plugin):
        t = template_format.parse(subscr_template)
        self.parse_stack(t)

        subscr = self.stack['MySubscription']
        subscr_id = "58138648c1e2eb7355d62137"

        self.m.StubOutWithMock(subscr, 'client')
        subscr.client().MultipleTimes().AndReturn(self.fc)

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        props = t['Resources']['MySubscription']['Properties']
        fake_subscr.ttl = props['ttl']
        fake_subscr.subscriber = props['subscriber']
        fake_subscr.options = props['options']

        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options={'key1': 'value1'},
                             subscriber=u'mailto:name@domain.com',
                             ttl=3600).AndReturn(fake_subscr)
        self.fc.subscription(
            subscr.properties['queue_name'], id=subscr_id,
            auto_create=False).MultipleTimes().AndReturn(fake_subscr)

        self.m.ReplayAll()

        rsrc_data = props.copy()
        rsrc_data['id'] = subscr_id
        scheduler.TaskRunner(subscr.create)()
        self.assertEqual(rsrc_data, subscr._show_resource())
        self.assertEqual(
            {'queue_name': props['queue_name'],
             'subscriber': props['subscriber'],
             'ttl': props['ttl'],
             'options': props['options']},
            subscr.parse_live_resource_data(subscr.properties,
                                            subscr._show_resource()))

        self.m.VerifyAll()


class JsonString(object):
    def __init__(self, data):
        self._data = data

    def __eq__(self, other):
        return self._data == jsonutils.loads(other)

    def __str__(self):
        return jsonutils.dumps(self._data)

    def __repr__(self):
        return str(self)


@mock.patch.object(resource.Resource, "client_plugin")
@mock.patch.object(resource.Resource, "client")
class ZaqarMistralTriggerTest(common.HeatTestCase):
    def setUp(self):
        super(ZaqarMistralTriggerTest, self).setUp()
        self.fc = self.m.CreateMockAnything()
        self.ctx = utils.dummy_context()
        self.patchobject(mistral_client_plugin.WorkflowConstraint,
                         'validate', return_value=True)

        stack_name = 'test_stack'
        t = template_format.parse(mistral_template)
        tmpl = template.Template(t)
        self.stack = stack.Stack(self.ctx, stack_name, tmpl)
        self.stack.validate()
        self.stack.store()

        def client(name='zaqar'):
            if name == 'mistral':
                client = mock.Mock()
                client.http_client = mock.Mock()
                client.http_client.base_url = 'http://mistral.example.net:8989'
                return client
            elif name == 'zaqar':
                return self.fc

        self.subscr = self.stack['subscription']
        self.subscr.client = mock.Mock(side_effect=client)

        self.subscriber = 'trust+http://mistral.example.net:8989/executions'
        self.options = {
            'post_data': JsonString({
                'workflow_id': 'abcd',
                'input': {"key1": "value1"},
                'params': {'env': {'notification': '$zaqar_message$'}},
            })
        }

    def test_create(self, mock_client, mock_plugin):
        subscr = self.subscr
        subscr_id = "58138648c1e2eb7355d62137"

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options=self.options,
                             subscriber=self.subscriber,
                             ttl=220367260800).AndReturn(fake_subscr)

        self.m.ReplayAll()

        scheduler.TaskRunner(subscr.create)()
        self.assertEqual(subscr_id, subscr.FnGetRefId())

        self.m.VerifyAll()

    def test_delete(self, mock_client, mock_plugin):
        subscr = self.subscr
        subscr_id = "58138648c1e2eb7355d62137"

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options=self.options,
                             subscriber=self.subscriber,
                             ttl=220367260800).AndReturn(fake_subscr)
        self.fc.subscription(subscr.properties['queue_name'],
                             id=subscr_id,
                             auto_create=False).AndReturn(fake_subscr)
        self.m.StubOutWithMock(fake_subscr, 'delete')
        fake_subscr.delete()

        self.m.ReplayAll()

        scheduler.TaskRunner(subscr.create)()
        scheduler.TaskRunner(subscr.delete)()

        self.m.VerifyAll()

    def test_delete_not_found(self, mock_client, mock_plugin):
        subscr = self.subscr
        subscr_id = "58138648c1e2eb7355d62137"

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options=self.options,
                             subscriber=self.subscriber,
                             ttl=220367260800).AndReturn(fake_subscr)
        self.fc.subscription(subscr.properties['queue_name'],
                             id=subscr_id,
                             auto_create=False).AndRaise(ResourceNotFound())

        self.m.ReplayAll()

        scheduler.TaskRunner(subscr.create)()
        scheduler.TaskRunner(subscr.delete)()

        self.m.VerifyAll()

    def test_update_in_place(self, mock_client, mock_plugin):
        subscr = self.subscr
        subscr_id = "58138648c1e2eb7355d62137"

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options=self.options,
                             subscriber=self.subscriber,
                             ttl=220367260800).AndReturn(fake_subscr)
        self.fc.subscription(subscr.properties['queue_name'],
                             id=subscr_id,
                             auto_create=False).AndReturn(fake_subscr)
        self.m.StubOutWithMock(fake_subscr, 'update')
        fake_subscr.update({'ttl': 3601, 'subscriber': self.subscriber,
                            'options': self.options})

        self.m.ReplayAll()

        t = template_format.parse(mistral_template)
        new_subscr = t['resources']['subscription']
        new_subscr['properties']['ttl'] = "3601"
        resource_defns = template.Template(t).resource_definitions(self.stack)

        scheduler.TaskRunner(subscr.create)()
        scheduler.TaskRunner(subscr.update, resource_defns['subscription'])()

        self.m.VerifyAll()

    def test_update_replace(self, mock_client, mock_plugin):
        subscr = self.subscr
        subscr_id = "58138648c1e2eb7355d62137"

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options=self.options,
                             subscriber=self.subscriber,
                             ttl=220367260800).AndReturn(fake_subscr)

        self.m.ReplayAll()

        t = template_format.parse(mistral_template)
        t['resources']['subscription']['properties']['queue_name'] = 'foo'
        resource_defns = template.Template(t).resource_definitions(self.stack)
        new_subscr = resource_defns['subscription']

        scheduler.TaskRunner(subscr.create)()
        err = self.assertRaises(resource.UpdateReplace,
                                scheduler.TaskRunner(subscr.update,
                                                     new_subscr))
        msg = 'The Resource subscription requires replacement.'
        self.assertEqual(msg, six.text_type(err))

        self.m.VerifyAll()

    def test_show_resource(self, mock_client, mock_plugin):
        subscr = self.subscr
        subscr_id = "58138648c1e2eb7355d62137"

        fake_subscr = FakeSubscription(subscr.properties['queue_name'],
                                       subscr_id)
        fake_subscr.ttl = 220367260800
        fake_subscr.subscriber = self.subscriber
        fake_subscr.options = {'post_data': str(self.options['post_data'])}

        self.m.StubOutWithMock(self.fc, 'subscription')
        self.fc.subscription(subscr.properties['queue_name'],
                             options=self.options,
                             subscriber=self.subscriber,
                             ttl=220367260800).AndReturn(fake_subscr)
        self.fc.subscription(
            subscr.properties['queue_name'], id=subscr_id,
            auto_create=False).MultipleTimes().AndReturn(fake_subscr)

        self.m.ReplayAll()

        props = self.stack.t.t['resources']['subscription']['properties']
        scheduler.TaskRunner(subscr.create)()
        self.assertEqual(
            {'queue_name': props['queue_name'],
             'id': subscr_id,
             'subscriber': self.subscriber,
             'options': self.options,
             'ttl': 220367260800},
            subscr._show_resource())
        self.assertEqual(
            {'queue_name': props['queue_name'],
             'workflow_id': props['workflow_id'],
             'input': props['input'],
             'params': {},
             'ttl': 220367260800},
            subscr.parse_live_resource_data(subscr.properties,
                                            subscr._show_resource()))
