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

from ceilometerclient import client as cc
from ceilometerclient import exc
from ceilometerclient.openstack.common.apiclient import exceptions as api_exc

from heat.engine.clients import client_plugin


class CeilometerClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = [exc, api_exc]

    service_types = [METERING, ALARMING] = ['metering', 'alarming']

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('ceilometer', 'endpoint_type')
        endpoint = self.url_for(service_type=self.METERING,
                                endpoint_type=endpoint_type)
        aodh_endpoint = self.url_for(service_type=self.ALARMING,
                                     endpoint_type=endpoint_type)
        args = {
            'auth_url': con.auth_url,
            'service_type': self.METERING,
            'project_id': con.tenant_id,
            'token': lambda: self.auth_token,
            'endpoint_type': endpoint_type,
            'os_endpoint': endpoint,
            'cacert': self._get_client_option('ceilometer', 'ca_file'),
            'cert_file': self._get_client_option('ceilometer', 'cert_file'),
            'key_file': self._get_client_option('ceilometer', 'key_file'),
            'insecure': self._get_client_option('ceilometer', 'insecure'),
            'aodh_endpoint': aodh_endpoint
        }

        return cc.get_client('2', **args)

    def is_not_found(self, ex):
        return isinstance(ex, (exc.HTTPNotFound, api_exc.NotFound))

    def is_over_limit(self, ex):
        return isinstance(ex, exc.HTTPOverLimit)

    def is_conflict(self, ex):
        return isinstance(ex, exc.HTTPConflict)
