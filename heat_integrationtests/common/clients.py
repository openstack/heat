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

import cinderclient.client
import heatclient.client
import keystoneclient.exceptions
import keystoneclient.v2_0.client
import neutronclient.v2_0.client
import novaclient.client

import logging

LOG = logging.getLogger(__name__)


class ClientManager(object):
    """
    Manager that provides access to the official python clients for
    calling various OpenStack APIs.
    """

    CINDERCLIENT_VERSION = '1'
    HEATCLIENT_VERSION = '1'
    NOVACLIENT_VERSION = '2'

    def __init__(self, conf):
        self.conf = conf
        self.identity_client = self._get_identity_client()
        self.orchestration_client = self._get_orchestration_client()
        self.compute_client = self._get_compute_client()
        self.network_client = self._get_network_client()
        self.volume_client = self._get_volume_client()

    def _get_orchestration_client(self):
        keystone = self._get_identity_client()
        region = self.conf.region
        token = keystone.auth_token
        try:
            endpoint = keystone.service_catalog.url_for(
                attr='region',
                filter_value=region,
                service_type='orchestration',
                endpoint_type='publicURL')
        except keystoneclient.exceptions.EndpointNotFound:
            return None
        else:
            return heatclient.client.Client(
                self.HEATCLIENT_VERSION,
                endpoint,
                token=token,
                username=self.conf.username,
                password=self.conf.password)

    def _get_identity_client(self):
        return keystoneclient.v2_0.client.Client(
            username=self.conf.username,
            password=self.conf.password,
            tenant_name=self.conf.tenant_name,
            auth_url=self.conf.auth_url,
            insecure=self.conf.disable_ssl_certificate_validation)

    def _get_compute_client(self):

        dscv = self.conf.disable_ssl_certificate_validation
        region = self.conf.region

        client_args = (
            self.conf.username,
            self.conf.password,
            self.conf.tenant_name,
            self.conf.auth_url
        )

        # Create our default Nova client to use in testing
        return novaclient.client.Client(
            self.NOVACLIENT_VERSION,
            *client_args,
            service_type='compute',
            endpoint_type='publicURL',
            region_name=region,
            no_cache=True,
            insecure=dscv,
            http_log_debug=True)

    def _get_network_client(self):
        auth_url = self.conf.auth_url
        dscv = self.conf.disable_ssl_certificate_validation

        return neutronclient.v2_0.client.Client(
            username=self.conf.username,
            password=self.conf.password,
            tenant_name=self.conf.tenant_name,
            endpoint_type='publicURL',
            auth_url=auth_url,
            insecure=dscv)

    def _get_volume_client(self):
        auth_url = self.conf.auth_url
        region = self.conf.region
        endpoint_type = 'publicURL'
        dscv = self.conf.disable_ssl_certificate_validation
        return cinderclient.client.Client(
            self.CINDERCLIENT_VERSION,
            self.conf.username,
            self.conf.password,
            self.conf.tenant_name,
            auth_url,
            region_name=region,
            endpoint_type=endpoint_type,
            insecure=dscv,
            http_log_debug=True)
