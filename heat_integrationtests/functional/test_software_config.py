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
import os
import subprocess
import sys
import tempfile
import time

from oslo_utils import timeutils

from heat_integrationtests.common import exceptions
from heat_integrationtests.functional import functional_base


class ZaqarSignalTransportTest(functional_base.FunctionalTestsBase):
    server_template = '''
heat_template_version: "2013-05-23"

parameters:
  flavor:
    type: string
  image:
    type: string
  network:
    type: string

resources:
  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      user_data_format: SOFTWARE_CONFIG
      software_config_transport: ZAQAR_MESSAGE
      networks: [{network: {get_param: network}}]
  config:
    type: OS::Heat::SoftwareConfig
    properties:
      config: echo 'foo'
  deployment:
    type: OS::Heat::SoftwareDeployment
    properties:
      config: {get_resource: config}
      server: {get_resource: server}
      signal_transport: ZAQAR_SIGNAL

outputs:
  data:
    value: {get_attr: [deployment, deploy_stdout]}
'''

    conf_template = '''
[zaqar]
user_id = %(user_id)s
password = %(password)s
project_id = %(project_id)s
auth_url = %(auth_url)s
queue_id = %(queue_id)s
    '''

    def test_signal_queues(self):
        parms = {'flavor': self.conf.minimal_instance_type,
                 'network': self.conf.fixed_network_name,
                 'image': self.conf.minimal_image_ref}
        stack_identifier = self.stack_create(
            parameters=parms,
            template=self.server_template,
            expected_status=None)
        metadata = self.wait_for_deploy_metadata_set(stack_identifier)
        config = metadata['os-collect-config']['zaqar']
        conf_content = self.conf_template % config
        fd, temp_path = tempfile.mkstemp()
        os.write(fd, conf_content.encode('utf-8'))
        os.close(fd)
        cmd = ['os-collect-config', '--one-time',
               '--config-file=%s' % temp_path, 'zaqar']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        stdout_value = proc.communicate()[0]
        data = json.loads(stdout_value.decode('utf-8'))
        self.assertEqual(config, data['zaqar']['os-collect-config']['zaqar'])
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        stdout_value = proc.communicate()[0]
        data = json.loads(stdout_value.decode('utf-8'))

        fd, temp_path = tempfile.mkstemp()
        os.write(fd,
                 json.dumps(data['zaqar']['deployments'][0]).encode('utf-8'))
        os.close(fd)
        cmd = [sys.executable, self.conf.heat_config_notify_script, temp_path]
        proc = subprocess.Popen(cmd,
                                stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE)
        proc.communicate(
            json.dumps({'deploy_stdout': 'here!'}).encode('utf-8'))
        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('here!', stack.outputs[0]['output_value'])

    def wait_for_deploy_metadata_set(self, stack):
        build_timeout = self.conf.build_timeout
        build_interval = self.conf.build_interval

        start = timeutils.utcnow()
        while timeutils.delta_seconds(start,
                                      timeutils.utcnow()) < build_timeout:
            server_metadata = self.client.resources.metadata(
                stack, 'server')
            if server_metadata.get('deployments'):
                return server_metadata
            time.sleep(build_interval)

        message = ('Deployment resources failed to be created within '
                   'the required time (%s s).' %
                   (build_timeout))
        raise exceptions.TimeoutException(message)
