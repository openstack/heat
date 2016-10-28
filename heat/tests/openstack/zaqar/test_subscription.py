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
from heat.engine import resource
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


class FakeSubscription(object):
    def __init__(self, queue_name, id=None, ttl=None, subscriber=None,
                 options=None, auto_create=True):
        self.id = id
        self.queue_name = queue_name
        self.ttl = ttl
        self.subscriber = subscriber
        self.options = options

    def update(self, prop_diff):
        pass

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
        t = template_format.parse(wp_template)
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
        t = template_format.parse(wp_template)
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
        t = template_format.parse(wp_template)
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
        t = template_format.parse(wp_template)
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
        t = template_format.parse(wp_template)
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
        fake_subscr.update({'ttl': 3601})

        self.m.ReplayAll()

        t = template_format.parse(wp_template)
        new_subscr = t['Resources']['MySubscription']
        new_subscr['Properties']['ttl'] = "3601"
        resource_defns = template.Template(t).resource_definitions(self.stack)

        scheduler.TaskRunner(subscr.create)()
        scheduler.TaskRunner(subscr.update, resource_defns['MySubscription'])()

        self.m.VerifyAll()

    def test_update_replace(self, mock_client, mock_plugin):
        t = template_format.parse(wp_template)
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

        t = template_format.parse(wp_template)
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
        t = template_format.parse(wp_template)
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
