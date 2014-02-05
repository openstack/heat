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

from heat.engine import clients
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)

try:
    from marconiclient.queues.v1 import client as marconiclient
except ImportError:
    marconiclient = None
    logger.info(_('marconiclient not available'))


class Clients(clients.OpenStackClients):
    '''
    Convenience class to create and cache client instances.
    '''
    def __init__(self, context):
        super(Clients, self).__init__(context)
        self._marconi = None

    def marconi(self, service_type="queuing"):
        if self._marconi:
            return self._marconi

        con = self.context
        if self.auth_token is None:
            logger.error(_("Marconi connection failed, no auth_token!"))
            return None

        opts = {
            'os_auth_token': con.auth_token,
            'os_auth_url': con.auth_url,
            'os_project_id': con.tenant,
            'os_service_type': service_type,
        }
        auth_opts = {'backend': 'keystone',
                     'options': opts}
        conf = {'auth_opts': auth_opts}
        endpoint = self.url_for(service_type=service_type)

        self._marconi = marconiclient.Client(url=endpoint, conf=conf)

        return self._marconi
