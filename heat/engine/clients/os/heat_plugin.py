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

from oslo_config import cfg

from heatclient import client as hc
from heatclient import exc

from heat.engine.clients import client_plugin

CLIENT_NAME = 'heat'


class HeatClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exc

    service_types = [ORCHESTRATION,
                     CLOUDFORMATION] = ['orchestration', 'cloudformation']

    def _create(self):
        endpoint = self.get_heat_url()
        args = {}
        if self._get_client_option(CLIENT_NAME, 'url'):
            # assume that the heat API URL is manually configured because
            # it is not in the keystone catalog, so include the credentials
            # for the standalone auth_password middleware
            args['username'] = self.context.username
            args['password'] = self.context.password

        return hc.Client('1', endpoint_override=endpoint,
                         session=self.context.keystone_session,
                         **args)

    def is_not_found(self, ex):
        return isinstance(ex, exc.HTTPNotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exc.HTTPOverLimit)

    def is_conflict(self, ex):
        return isinstance(ex, exc.HTTPConflict)

    def get_heat_url(self):
        heat_url = self._get_client_option(CLIENT_NAME, 'url')
        if heat_url:
            tenant_id = self.context.tenant_id
            heat_url = heat_url % {'tenant_id': tenant_id}
        else:
            endpoint_type = self._get_client_option(CLIENT_NAME,
                                                    'endpoint_type')
            heat_url = self.url_for(service_type=self.ORCHESTRATION,
                                    endpoint_type=endpoint_type)
        return heat_url

    def get_heat_cfn_url(self):
        endpoint_type = self._get_client_option(CLIENT_NAME,
                                                'endpoint_type')
        heat_cfn_url = self.url_for(service_type=self.CLOUDFORMATION,
                                    endpoint_type=endpoint_type)
        return heat_cfn_url

    def get_cfn_metadata_server_url(self):
        # Historically, we've required heat_metadata_server_url set in
        # heat.conf, which simply points to the heat-api-cfn endpoint in
        # most cases, so fall back to looking in the catalog when not set
        config_url = cfg.CONF.heat_metadata_server_url
        if config_url is None:
            config_url = self.get_heat_cfn_url()
        # Backwards compatibility, previous heat_metadata_server_url
        # values didn't have to include the version path suffix
        # Also, we always added a trailing "/" in nova/server.py,
        # which looks not required by os-collect-config, but maintain
        # to avoid any risk other folks have scripts which expect it.
        if '/v1' not in config_url:
            config_url += '/v1'
        if config_url and config_url[-1] != "/":
            config_url += '/'
        return config_url

    def get_insecure_option(self):
        return self._get_client_option(CLIENT_NAME, 'insecure')
