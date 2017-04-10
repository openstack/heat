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

import kombu
from oslo_config import cfg
from oslo_messaging._drivers import common
from oslo_messaging import transport
import requests

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base

BASIC_NOTIFICATIONS = [
    'orchestration.stack.create.start',
    'orchestration.stack.create.end',
    'orchestration.stack.update.start',
    'orchestration.stack.update.end',
    'orchestration.stack.suspend.start',
    'orchestration.stack.suspend.end',
    'orchestration.stack.resume.start',
    'orchestration.stack.resume.end',
    'orchestration.stack.delete.start',
    'orchestration.stack.delete.end'
]

ASG_NOTIFICATIONS = [
    'orchestration.autoscaling.start',
    'orchestration.autoscaling.end'
]


def get_url(conf):
    conf = conf.oslo_messaging_rabbit
    return 'amqp://%s:%s@%s:%s/' % (conf.rabbit_userid,
                                    conf.rabbit_password,
                                    conf.rabbit_host,
                                    conf.rabbit_port)


class NotificationHandler(object):
    def __init__(self, stack_id, events=None):
        self._notifications = []
        self.stack_id = stack_id
        self.events = events

    def process_message(self, body, message):
        notification = common.deserialize_msg(body)
        if notification['payload']['stack_name'] == self.stack_id:
            if self.events is not None:
                if notification['event_type'] in self.events:
                    self.notifications.append(notification['event_type'])
            else:
                self.notifications.append(notification['event_type'])
        message.ack()

    def clear(self):
        self._notifications = []

    @property
    def notifications(self):
        return self._notifications


class NotificationTest(functional_base.FunctionalTestsBase):

    basic_template = '''
heat_template_version: 2013-05-23
resources:
  random1:
    type: OS::Heat::RandomString
'''
    update_basic_template = '''
heat_template_version: 2013-05-23
resources:
  random1:
    type: OS::Heat::RandomString
  random2:
    type: OS::Heat::RandomString
'''

    asg_template = '''
heat_template_version: 2013-05-23
resources:
  asg:
    type: OS::Heat::AutoScalingGroup
    properties:
      resource:
        type: OS::Heat::RandomString
      min_size: 1
      desired_capacity: 2
      max_size: 3

  scale_up_policy:
    type: OS::Heat::ScalingPolicy
    properties:
      adjustment_type: change_in_capacity
      auto_scaling_group_id: {get_resource: asg}
      cooldown: 0
      scaling_adjustment: 1

  scale_down_policy:
    type: OS::Heat::ScalingPolicy
    properties:
      adjustment_type: change_in_capacity
      auto_scaling_group_id: {get_resource: asg}
      cooldown: 0
      scaling_adjustment: '-1'

outputs:
  scale_up_url:
    value: {get_attr: [scale_up_policy, alarm_url]}
  scale_dn_url:
    value: {get_attr: [scale_down_policy, alarm_url]}
'''

    def setUp(self):
        super(NotificationTest, self).setUp()
        self.exchange = kombu.Exchange('heat', 'topic', durable=False)
        queue = kombu.Queue(exchange=self.exchange,
                            routing_key='notifications.info',
                            exclusive=True)
        self.conn = kombu.Connection(get_url(
            transport.get_transport(cfg.CONF).conf))
        self.ch = self.conn.channel()
        self.queue = queue(self.ch)
        self.queue.declare()

    def consume_events(self, handler, count):
        self.conn.drain_events()
        return len(handler.notifications) == count

    def test_basic_notifications(self):
        # disable cleanup so we can call _stack_delete() directly.
        stack_identifier = self.stack_create(template=self.basic_template,
                                             enable_cleanup=False)
        self.update_stack(stack_identifier,
                          template=self.update_basic_template)
        self.stack_suspend(stack_identifier)
        self.stack_resume(stack_identifier)
        self._stack_delete(stack_identifier)

        handler = NotificationHandler(stack_identifier.split('/')[0])

        with self.conn.Consumer(self.queue,
                                callbacks=[handler.process_message],
                                auto_declare=False):
            try:
                while True:
                    self.conn.drain_events(timeout=1)
            except Exception:
                pass

        for n in BASIC_NOTIFICATIONS:
            self.assertIn(n, handler.notifications)

    def test_asg_notifications(self):
        stack_identifier = self.stack_create(template=self.asg_template)

        for output in self.client.stacks.get(stack_identifier).outputs:
            if output['output_key'] == 'scale_dn_url':
                scale_down_url = output['output_value']
            else:
                scale_up_url = output['output_value']

        notifications = []
        handler = NotificationHandler(stack_identifier.split('/')[0],
                                      ASG_NOTIFICATIONS)

        with self.conn.Consumer(self.queue,
                                callbacks=[handler.process_message],
                                auto_declare=False):

            requests.post(scale_up_url, verify=self.verify_cert)
            self.assertTrue(
                test.call_until_true(20, 0, self.consume_events, handler, 2))
            notifications += handler.notifications

            handler.clear()
            requests.post(scale_down_url, verify=self.verify_cert)
            self.assertTrue(
                test.call_until_true(20, 0, self.consume_events, handler, 2))
            notifications += handler.notifications

        self.assertEqual(2, notifications.count(ASG_NOTIFICATIONS[0]))
        self.assertEqual(2, notifications.count(ASG_NOTIFICATIONS[1]))
