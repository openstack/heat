#
# Copyright (c) 2013 Docker, Inc.
# All Rights Reserved.
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
import random
import string


class APIError(Exception):
    def __init__(self, content, response):
        super(APIError, self).__init__(content)
        self.response = response


errors = mock.MagicMock()
errors.APIError = APIError


class FakeResponse (object):
    def __init__(self, status_code=200, reason='OK'):
        self.status_code = status_code
        self.reason = reason
        self.content = reason


class Client(object):

    def __init__(self, endpoint=None):
        self._endpoint = endpoint
        self._containers = {}
        self.pulled_images = []
        self.container_create = []
        self.container_start = []
        self.version_info = {}

    def _generate_string(self, n=32):
        return ''.join(random.choice(string.ascii_lowercase) for i in range(n))

    def _check_exists(self, container_id):
        if container_id not in self._containers:
            raise APIError(
                '404 Client Error: Not Found ("No such container: '
                '{0}")'.format(container_id),
                FakeResponse(status_code=404,
                             reason='No such container'))

    def _set_running(self, container_id, running):
        self._check_exists(container_id)
        self._containers[container_id] = running

    def inspect_container(self, container_id):
        self._check_exists(container_id)
        info = {
            'Id': container_id,
            'NetworkSettings': {
                'Bridge': 'docker0',
                'Gateway': '172.17.42.1',
                'IPAddress': '172.17.0.3',
                'IPPrefixLen': 16,
                'Ports': {
                    '80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '1080'}]
                }
            },
            'State': {
                'Running': self._containers[container_id]
            }
        }
        return info

    def logs(self, container_id):
        logs = ['---logs_begin---']
        for i in range(random.randint(1, 20)):
            logs.append(self._generate_string(random.randint(5, 42)))
        logs.append('---logs_end---')
        return '\n'.join(logs)

    def create_container(self, **kwargs):
        self.container_create.append(kwargs)
        container_id = self._generate_string()
        self._containers[container_id] = None
        self._set_running(container_id, False)
        return self.inspect_container(container_id)

    def remove_container(self, container_id, **kwargs):
        self._check_exists(container_id)
        del self._containers[container_id]

    def start(self, container_id, **kwargs):
        self.container_start.append(kwargs)
        self._set_running(container_id, True)

    def stop(self, container_id):
        self._set_running(container_id, False)

    def kill(self, container_id):
        self._set_running(container_id, False)

    def pull(self, image):
        self.pulled_images.append(image)

    def version(self, api_version=True):
        if not self.version_info:
            self.version_info['ApiVersion'] = '1.15'
        return self.version_info

    def set_api_version(self, version):
        self.version_info['ApiVersion'] = version
