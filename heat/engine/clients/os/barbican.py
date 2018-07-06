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

from barbicanclient import exceptions
from barbicanclient.v1 import client as barbican_client
from barbicanclient.v1 import containers
from oslo_log import log as logging

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine import constraints

LOG = logging.getLogger(__name__)

CLIENT_NAME = 'barbican'


class BarbicanClientPlugin(client_plugin.ClientPlugin):

    service_types = [KEY_MANAGER] = ['key-manager']

    def _create(self):
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        client = barbican_client.Client(
            session=self.context.keystone_session,
            service_type=self.KEY_MANAGER,
            interface=interface,
            region_name=self._get_region_name())
        return client

    def is_not_found(self, ex):
        return (isinstance(ex, exceptions.HTTPClientError) and
                ex.status_code == 404)

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
            secret = self.client().secrets.get(secret_ref)
            # Force lazy loading. TODO(therve): replace with to_dict()
            secret.name
            return secret
        except Exception as ex:
            if self.is_not_found(ex):
                raise exception.EntityNotFound(
                    entity="Secret",
                    name=secret_ref)
            LOG.info('Failed to get Barbican secret from reference %s' % (
                secret_ref))
            raise

    def get_secret_payload_by_ref(self, secret_ref):
        return self.get_secret_by_ref(secret_ref).payload

    def get_container_by_ref(self, container_ref):
        try:
            # TODO(therve): replace with to_dict()
            return self.client().containers.get(container_ref)
        except Exception as ex:
            if self.is_not_found(ex):
                raise exception.EntityNotFound(
                    entity="Container",
                    name=container_ref)
            raise


class SecretConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_secret_by_ref'
    expected_exceptions = (exception.EntityNotFound,)


class ContainerConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_container_by_ref'
    expected_exceptions = (exception.EntityNotFound,)
