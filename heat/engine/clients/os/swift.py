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

import hashlib
import random
import time
import urlparse

from swiftclient import client as sc
from swiftclient import exceptions
from swiftclient import utils as swiftclient_utils

from heat.engine.clients import client_plugin

IN_PROGRESS = 'in progress'

MAX_EPOCH = 2147483647


class SwiftClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('swift', 'endpoint_type')
        args = {
            'auth_version': '2.0',
            'tenant_name': con.tenant,
            'user': con.username,
            'key': None,
            'authurl': None,
            'preauthtoken': self.auth_token,
            'preauthurl': self.url_for(service_type='object-store',
                                       endpoint_type=endpoint_type),
            'os_options': {'endpoint_type': endpoint_type},
            'cacert': self._get_client_option('swift', 'ca_file'),
            'insecure': self._get_client_option('swift', 'insecure')
        }
        return sc.Connection(**args)

    def is_client_exception(self, ex):
        return isinstance(ex, exceptions.ClientException)

    def is_not_found(self, ex):
        return (isinstance(ex, exceptions.ClientException) and
                ex.http_status == 404)

    def is_over_limit(self, ex):
        return (isinstance(ex, exceptions.ClientException) and
                ex.http_status == 413)

    def is_conflict(self, ex):
        return (isinstance(ex, exceptions.ClientException) and
                ex.http_status == 409)

    @staticmethod
    def is_valid_temp_url_path(path):
        '''Return True if path is a valid Swift TempURL path, False otherwise.

        A Swift TempURL path must:
        - Be five parts, ['', 'v1', 'account', 'container', 'object']
        - Be a v1 request
        - Have account, container, and object values
        - Have an object value with more than just '/'s

        :param path: The TempURL path
        :type path: string
        '''
        parts = path.split('/', 4)
        return bool(len(parts) == 5 and
                    not parts[0] and
                    parts[1] == 'v1' and
                    parts[2] and
                    parts[3] and
                    parts[4].strip('/'))

    def get_temp_url(self, container_name, obj_name, timeout=None,
                     method='PUT'):
        '''
        Return a Swift TempURL.
        '''
        key_header = 'x-account-meta-temp-url-key'
        if key_header in self.client().head_account():
            key = self.client().head_account()[key_header]
        else:
            key = hashlib.sha224(str(random.getrandbits(256))).hexdigest()[:32]
            self.client().post_account({key_header: key})

        path = '/v1/AUTH_%s/%s/%s' % (self.context.tenant_id, container_name,
                                      obj_name)
        if timeout is None:
            timeout = MAX_EPOCH - 60 - time.time()
        tempurl = swiftclient_utils.generate_temp_url(path, timeout, key,
                                                      method)
        sw_url = urlparse.urlparse(self.client().url)
        return '%s://%s%s' % (sw_url.scheme, sw_url.netloc, tempurl)

    def get_signal_url(self, container_name, obj_name, timeout=None):
        '''
        Turn on object versioning so we can use a single TempURL for
        multiple signals and return a Swift TempURL.
        '''
        self.client().put_container(
            container_name, headers={'x-versions-location': container_name})
        self.client().put_object(container_name, obj_name, IN_PROGRESS)

        return self.get_temp_url(container_name, obj_name, timeout)
