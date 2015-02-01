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

from oslo.utils import importutils

from heat.engine.clients import client_plugin

mistral_base = importutils.try_import('mistralclient.api.base')
mistral_client = importutils.try_import('mistralclient.api.client')


class MistralClientPlugin(client_plugin.ClientPlugin):

    def _create(self):
        endpoint_type = self._get_client_option('mistral', 'endpoint_type')
        endpoint = self.url_for(service_type='workflowv2',
                                endpoint_type=endpoint_type)

        args = {
            'mistral_url': endpoint,
            'auth_token': self.auth_token
        }

        client = mistral_client.client(**args)
        return client

    def is_not_found(self, ex):
        return (isinstance(ex, mistral_base.APIException) and
                ex.error_code == 404)

    def is_over_limit(self, ex):
        return (isinstance(ex, mistral_base.APIException) and
                ex.error_code == 413)

    def is_conflict(self, ex):
        return (isinstance(ex, mistral_base.APIException) and
                ex.error_code == 409)
