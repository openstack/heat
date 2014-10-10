# Copyright (c) 2014 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from saharaclient.api import base as sahara_base
from saharaclient import client as sahara_client

from heat.engine.clients import client_plugin


class SaharaClientPlugin(client_plugin.ClientPlugin):

    def _create(self):
        con = self.context
        endpoint_type = self._get_client_option('sahara', 'endpoint_type')
        endpoint = self.url_for(service_type='data_processing',
                                endpoint_type=endpoint_type)
        args = {
            'service_type': 'data_processing',
            'input_auth_token': self.auth_token,
            'auth_url': con.auth_url,
            'project_name': con.tenant,
            'sahara_url': endpoint
        }
        client = sahara_client.Client('1.1', **args)
        return client

    def is_not_found(self, ex):
        return (isinstance(ex, sahara_base.APIException) and
                ex.error_code == 404)

    def is_over_limit(self, ex):
        return (isinstance(ex, sahara_base.APIException) and
                ex.error_code == 413)

    def is_conflict(self, ex):
        return (isinstance(ex, sahara_base.APIException) and
                ex.error_code == 409)
