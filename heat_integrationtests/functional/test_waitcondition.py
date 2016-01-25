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

import json

from keystoneclient.v3 import client as keystoneclient
from zaqarclient.queues.v1 import client as zaqarclient

from heat_integrationtests.functional import functional_base


class ZaqarWaitConditionTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: "2013-05-23"

resources:
  wait_condition:
    type: OS::Heat::WaitCondition
    properties:
      handle: {get_resource: wait_handle}
      timeout: 120
  wait_handle:
    type: OS::Heat::WaitConditionHandle
    properties:
      signal_transport: ZAQAR_SIGNAL

outputs:
  wait_data:
   value: {'Fn::Select': ['data_id', {get_attr: [wait_condition, data]}]}
'''

    def test_signal_queues(self):
        stack_identifier = self.stack_create(
            template=self.template,
            expected_status=None)
        self._wait_for_resource_status(stack_identifier, 'wait_handle',
                                       'CREATE_COMPLETE')
        resource = self.client.resources.get(stack_identifier, 'wait_handle')
        signal = json.loads(resource.attributes['signal'])
        ks = keystoneclient.Client(
            auth_url=signal['auth_url'],
            user_id=signal['user_id'],
            password=signal['password'],
            project_id=signal['project_id'])
        endpoint = ks.service_catalog.url_for(
            service_type='messaging', endpoint_type='publicURL')
        conf = {
            'auth_opts': {
                'backend': 'keystone',
                'options': {
                    'os_auth_token': ks.auth_token,
                    'os_project_id': signal['project_id']
                }
            }
        }

        zaqar = zaqarclient.Client(endpoint, conf=conf, version=1.1)

        queue = zaqar.queue(signal['queue_id'])
        queue.post({'body': {'data': 'here!', 'id': 'data_id'}, 'ttl': 600})
        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('here!', stack.outputs[0]['output_value'])
