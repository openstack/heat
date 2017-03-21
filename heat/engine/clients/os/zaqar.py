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

import six

from oslo_log import log as logging
from zaqarclient.queues.v2 import client as zaqarclient
from zaqarclient.transport import errors as zaqar_errors

from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine import constraints

LOG = logging.getLogger(__name__)

CLIENT_NAME = 'zaqar'


class ZaqarClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = zaqar_errors

    service_types = [MESSAGING] = ['messaging']

    DEFAULT_TTL = 3600

    def _create(self):
        return zaqarclient.Client(version=2,
                                  session=self.context.keystone_session)

    def create_for_tenant(self, tenant_id, token):
        con = self.context
        if token is None:
            LOG.error("Zaqar connection failed, no auth_token!")
            return None

        opts = {
            'os_auth_token': token,
            'os_auth_url': con.auth_url,
            'os_project_id': tenant_id,
            'os_service_type': self.MESSAGING,
        }
        auth_opts = {'backend': 'keystone',
                     'options': opts}
        conf = {'auth_opts': auth_opts}
        endpoint = self.url_for(service_type=self.MESSAGING)
        return zaqarclient.Client(url=endpoint, conf=conf, version=2)

    def create_from_signed_url(self, project_id, paths, expires, methods,
                               signature):
        opts = {
            'paths': paths,
            'expires': expires,
            'methods': methods,
            'signature': signature,
            'os_project_id': project_id,
        }
        auth_opts = {'backend': 'signed-url',
                     'options': opts}
        conf = {'auth_opts': auth_opts}
        endpoint = self.url_for(service_type=self.MESSAGING)
        return zaqarclient.Client(url=endpoint, conf=conf, version=2)

    def is_not_found(self, ex):
        return isinstance(ex, zaqar_errors.ResourceNotFound)

    def get_queue(self, queue_name):
        if not isinstance(queue_name, six.string_types):
            raise TypeError(_('Queue name must be a string'))
        if not (0 < len(queue_name) <= 64):
            raise ValueError(_('Queue name length must be 1-64'))
        # Queues are created automatically starting with v1.1 of the Zaqar API,
        # so any queue name is valid for the purposes of constraint validation.
        return queue_name


class ZaqarEventSink(object):

    def __init__(self, target, ttl=None):
        self._target = target
        self._ttl = ttl

    def consume(self, context, event):
        zaqar_plugin = context.clients.client_plugin('zaqar')
        zaqar = zaqar_plugin.client()
        queue = zaqar.queue(self._target, auto_create=False)
        ttl = self._ttl if self._ttl is not None else zaqar_plugin.DEFAULT_TTL
        queue.post({'body': event, 'ttl': ttl})


class QueueConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_queue'
