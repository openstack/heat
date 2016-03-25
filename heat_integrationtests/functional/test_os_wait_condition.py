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

from heat_integrationtests.functional import functional_base


class OSWaitCondition(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: 2013-05-23
parameters:
  flavor:
    type: string
  image:
    type: string
  network:
    type: string
  timeout:
    type: number
    default: 60
resources:
  instance1:
    type: OS::Nova::Server
    properties:
      flavor: {get_param: flavor}
      image: {get_param: image}
      networks:
      - network: {get_param: network}
      user_data_format: RAW
      user_data:
        str_replace:
          template: '#!/bin/sh

            wc_notify --data-binary ''{"status": "SUCCESS"}''

            # signals with reason

            wc_notify --data-binary ''{"status": "SUCCESS", "reason":
            "signal2"}''

            # signals with data

            wc_notify --data-binary ''{"status": "SUCCESS", "reason":
            "signal3", "data": "data3"}''

            wc_notify --data-binary ''{"status": "SUCCESS", "reason":
            "signal4", "data": "data4"}''

            # check signals with the same number

            wc_notify --data-binary ''{"status": "SUCCESS", "id": "5"}''

            wc_notify --data-binary ''{"status": "SUCCESS", "id": "5"}''

            # loop for 25 signals without reasons and data

            for i in `seq 1 25`; do wc_notify --data-binary ''{"status":
            "SUCCESS"}'' & done

            wait
            '
          params:
            wc_notify:
              get_attr: [wait_handle, curl_cli]

  wait_condition:
    type: OS::Heat::WaitCondition
    depends_on: instance1
    properties:
      count: 30
      handle: {get_resource: wait_handle}
      timeout: {get_param: timeout}

  wait_handle:
    type: OS::Heat::WaitConditionHandle

outputs:
  curl_cli:
    value:
      get_attr: [wait_handle, curl_cli]
  wc_data:
    value:
      get_attr: [wait_condition, data]
'''

    def setUp(self):
        super(OSWaitCondition, self).setUp()
        if not self.conf.minimal_image_ref:
            raise self.skipException("No minimal image configured to test")
        if not self.conf.minimal_instance_type:
            raise self.skipException("No minimal flavor configured to test")

    def test_create_stack_with_multi_signal_waitcondition(self):
        params = {'flavor': self.conf.minimal_instance_type,
                  'image': self.conf.minimal_image_ref,
                  'network': self.conf.fixed_network_name}
        self.stack_create(template=self.template, parameters=params)
