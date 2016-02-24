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

import uuid

from zaqarclient.queues.v1 import client as zaqarclient

from heat_integrationtests.functional import functional_base


class ZaqarEventSinkTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: "2013-05-23"
resources:
  test_resource:
    type: OS::Heat::TestResource
    properties:
      value: ok
'''

    def test_events(self):
        queue_id = str(uuid.uuid4())
        environment = {'event_sinks': [{'type': 'zaqar-queue',
                                        'target': queue_id,
                                        'ttl': 120}]}
        stack_identifier = self.stack_create(
            template=self.template,
            environment=environment)
        stack_name, stack_id = stack_identifier.split('/')
        conf = {
            'auth_opts': {
                'backend': 'keystone',
                'options': {
                    'os_username': self.conf.username,
                    'os_password': self.conf.password,
                    'os_project_name': self.conf.tenant_name,
                    'os_auth_url': self.conf.auth_url
                }
            }
        }

        zaqar = zaqarclient.Client(conf=conf, version=1.1)
        queue = zaqar.queue(queue_id)
        messages = list(queue.messages())
        self.assertEqual(4, len(messages))
        types = [m.body['type'] for m in messages]
        self.assertEqual(['os.heat.event'] * 4, types)
        resources = set([m.body['payload']['resource_name'] for m in messages])
        self.assertEqual(set([stack_name, 'test_resource']), resources)
        stack_ids = [m.body['payload']['stack_id'] for m in messages]
        self.assertEqual([stack_id] * 4, stack_ids)
        statuses = [m.body['payload']['resource_status'] for m in messages]
        self.assertEqual(
            ['IN_PROGRESS', 'IN_PROGRESS', 'COMPLETE', 'COMPLETE'], statuses)
        actions = [m.body['payload']['resource_action'] for m in messages]
        self.assertEqual(['CREATE'] * 4, actions)
