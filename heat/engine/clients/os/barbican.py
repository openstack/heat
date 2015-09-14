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
from barbicanclient import client as barbican_client
from barbicanclient import containers
import six

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'barbican'


class BarbicanClientPlugin(client_plugin.ClientPlugin):

    service_types = [KEY_MANAGER] = ['key-manager']

    def _create(self):
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        endpoint = self.url_for(service_type=self.KEY_MANAGER,
                                endpoint_type=endpoint_type)
        self._keystone_session.auth = self.context.auth_plugin
        client = barbican_client.Client(
            session=self._keystone_session, endpoint=endpoint)

        return client

    def is_not_found(self, ex):
        # This is the only exception the client raises
        # Inspecting the message to see if it's a 'Not Found'
        return 'Not Found' in six.text_type(ex)

    def create_generic_container(self, **props):
        return containers.Container(
            self.client().containers._api, **props)

    def create_certificate(self, **props):
        return containers.CertificateContainer(
            self.client().containers._api, **props)

    def create_rsa(self, **props):
        return containers.RSAContainer(
            self.client().containers._api, **props)

    def get_secret_by_ref(self, secret_ref):
        try:
            return self.client().secrets.get(
                secret_ref)._get_formatted_entity()
        except Exception as ex:
            if self.is_not_found(ex):
                raise exception.EntityNotFound(
                    entity="Secret",
                    name=secret_ref)
            raise ex


class SecretConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_secret_by_ref'
    expected_exceptions = (exception.EntityNotFound,)
