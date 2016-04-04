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

import os

import ceilometerclient.client
import cinderclient.client
import heatclient.client
import keystoneclient.exceptions
import keystoneclient.v2_0.client
import neutronclient.v2_0.client
import novaclient.client
import swiftclient


class ClientManager(object):
    """
    Manager that provides access to the official python clients for
    calling various OpenStack APIs.
    """

    CINDERCLIENT_VERSION = '1'
    HEATCLIENT_VERSION = '1'
    NOVACLIENT_VERSION = '2'
    CEILOMETER_VERSION = '2'

    def __init__(self, conf):
        self.conf = conf
        self.insecure = self.conf.disable_ssl_certificate_validation
        self.ca_file = self.conf.ca_file
        self.identity_client = self._get_identity_client()
        self.orchestration_client = self._get_orchestration_client()
        self.compute_client = self._get_compute_client()
        self.network_client = self._get_network_client()
        self.volume_client = self._get_volume_client()
        self.object_client = self._get_object_client()
        self.metering_client = self._get_metering_client()

    def _get_orchestration_client(self):
        region = self.conf.region
        endpoint = os.environ.get('HEAT_URL')
        if os.environ.get('OS_NO_CLIENT_AUTH') == 'True':
            token = None
        else:
            keystone = self._get_identity_client()
            token = keystone.auth_token
        try:
            if endpoint is None:
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
            insecure=self.insecure,
            cacert=self.ca_file)

    def _get_compute_client(self):

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
            insecure=self.insecure,
            cacert=self.ca_file,
            http_log_debug=True)

    def _get_network_client(self):
        auth_url = self.conf.auth_url

        return neutronclient.v2_0.client.Client(
            username=self.conf.username,
            password=self.conf.password,
            tenant_name=self.conf.tenant_name,
            endpoint_type='publicURL',
            auth_url=auth_url,
            insecure=self.insecure,
            ca_cert=self.ca_file)

    def _get_volume_client(self):
        auth_url = self.conf.auth_url
        region = self.conf.region
        endpoint_type = 'publicURL'
        return cinderclient.client.Client(
            self.CINDERCLIENT_VERSION,
            self.conf.username,
            self.conf.password,
            self.conf.tenant_name,
            auth_url,
            region_name=region,
            endpoint_type=endpoint_type,
            insecure=self.insecure,
            cacert=self.ca_file,
            http_log_debug=True)

    def _get_object_client(self):
        args = {
            'auth_version': '2.0',
            'tenant_name': self.conf.tenant_name,
            'user': self.conf.username,
            'key': self.conf.password,
            'authurl': self.conf.auth_url,
            'os_options': {'endpoint_type': 'publicURL'},
            'insecure': self.insecure,
            'cacert': self.ca_file,
        }
        return swiftclient.client.Connection(**args)

    def _get_metering_client(self):

        keystone = self._get_identity_client()
        try:
            endpoint = keystone.service_catalog.url_for(
                attr='region',
                filter_value=self.conf.region,
                service_type='metering',
                endpoint_type='publicURL')

        except keystoneclient.exceptions.EndpointNotFound:
            return None
        else:
            args = {
                'username': self.conf.username,
                'password': self.conf.password,
                'tenant_name': self.conf.tenant_name,
                'auth_url': self.conf.auth_url,
                'insecure': self.insecure,
                'cacert': self.ca_file,
                'region_name': self.conf.region,
                'endpoint_type': 'publicURL',
                'service_type': 'metering',
            }

            return ceilometerclient.client.Client(self.CEILOMETER_VERSION,
                                                  endpoint, **args)
