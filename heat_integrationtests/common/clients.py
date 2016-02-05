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
from keystoneclient.auth.identity.generic import password
import keystoneclient.client
import keystoneclient.exceptions
from keystoneclient import session
import neutronclient.v2_0.client
import novaclient.client
import swiftclient


class KeystoneWrapperClient(object):
    """Wrapper object for keystone client

    This Wraps keystone client,so we can encpasulate certain
    added properties like auth_token, project_id etc.
    """
    def __init__(self, auth_plugin, verify=True):
        self.auth_plugin = auth_plugin
        self.session = session.Session(
            auth=auth_plugin,
            verify=verify)

    @property
    def auth_token(self):
        return self.auth_plugin.get_token(self.session)

    @property
    def auth_ref(self):
        return self.auth_plugin.get_access(self.session)

    @property
    def project_id(self):
        return self.auth_plugin.get_project_id(self.session)

    def get_endpoint_url(self, service_type, region=None):
        kwargs = {
            'service_type': service_type,
            'endpoint_type': 'publicURL'}
        if region:
            kwargs.update({'attr': 'region',
                           'filter_value': region})
        return self.auth_ref.service_catalog.url_for(**kwargs)


class ClientManager(object):
    """Provides access to the official python clients for calling various APIs.

    Manager that provides access to the official python clients for
    calling various OpenStack APIs.
    """

    CINDERCLIENT_VERSION = '2'
    HEATCLIENT_VERSION = '1'
    NOVACLIENT_VERSION = '2'
    CEILOMETER_VERSION = '2'

    def __init__(self, conf):
        self.conf = conf
        self.v2_auth_url = self.conf.auth_url.replace('/v3', '/v2.0')
        self.auth_version = self.conf.auth_url.split('/v')[1]
        self.identity_client = self._get_identity_client()
        self.orchestration_client = self._get_orchestration_client()
        self.compute_client = self._get_compute_client()
        self.network_client = self._get_network_client()
        self.volume_client = self._get_volume_client()
        self.object_client = self._get_object_client()
        self.metering_client = self._get_metering_client()

    def _get_orchestration_client(self):
        endpoint = os.environ.get('HEAT_URL')
        if os.environ.get('OS_NO_CLIENT_AUTH') == 'True':
            token = None
        else:
            token = self.identity_client.auth_token
        try:
            if endpoint is None:
                endpoint = self.identity_client.get_endpoint_url(
                    'orchestration', self.conf.region)
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
        domain = self.conf.domain_name
        kwargs = {
            'username': self.conf.username,
            'password': self.conf.password,
            'tenant_name': self.conf.tenant_name,
            'auth_url': self.conf.auth_url
        }
        # keystone v2 can't ignore domain details
        if self.auth_version == '3':
            kwargs.update({
                'project_domain_name': domain,
                'user_domain_name': domain})
        auth = password.Password(**kwargs)
        return KeystoneWrapperClient(
            auth,
            not self.conf.disable_ssl_certificate_validation)

    def _get_compute_client(self):

        dscv = self.conf.disable_ssl_certificate_validation
        region = self.conf.region

        client_args = (
            self.conf.username,
            self.conf.password,
            self.conf.tenant_name,
            # novaclient can not use v3 url
            self.v2_auth_url
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
        dscv = self.conf.disable_ssl_certificate_validation

        return neutronclient.v2_0.client.Client(
            username=self.conf.username,
            password=self.conf.password,
            tenant_name=self.conf.tenant_name,
            endpoint_type='publicURL',
            # neutronclient can not use v3 url
            auth_url=self.v2_auth_url,
            insecure=dscv)

    def _get_volume_client(self):
        region = self.conf.region
        endpoint_type = 'publicURL'
        dscv = self.conf.disable_ssl_certificate_validation
        return cinderclient.client.Client(
            self.CINDERCLIENT_VERSION,
            self.conf.username,
            self.conf.password,
            self.conf.tenant_name,
            # cinderclient can not use v3 url
            self.v2_auth_url,
            region_name=region,
            endpoint_type=endpoint_type,
            insecure=dscv,
            http_log_debug=True)

    def _get_object_client(self):
        dscv = self.conf.disable_ssl_certificate_validation
        args = {
            'auth_version': self.auth_version,
            'tenant_name': self.conf.tenant_name,
            'user': self.conf.username,
            'key': self.conf.password,
            'authurl': self.conf.auth_url,
            'os_options': {'endpoint_type': 'publicURL'},
            'insecure': dscv,
        }
        return swiftclient.client.Connection(**args)

    def _get_metering_client(self):
        dscv = self.conf.disable_ssl_certificate_validation
        domain = self.conf.domain_name
        try:
            endpoint = self.identity_client.get_endpoint_url('metering',
                                                             self.conf.region)
        except keystoneclient.exceptions.EndpointNotFound:
            return None
        else:
            args = {
                'username': self.conf.username,
                'password': self.conf.password,
                'tenant_name': self.conf.tenant_name,
                'auth_url': self.conf.auth_url,
                'insecure': dscv,
                'region_name': self.conf.region,
                'endpoint_type': 'publicURL',
                'service_type': 'metering',
            }
            # ceilometerclient can't ignore domain details for
            # v2 auth_url
            if self.auth_version == '3':
                args.update(
                    {'user_domain_name': domain,
                     'project_domain_name': domain})

            return ceilometerclient.client.Client(self.CEILOMETER_VERSION,
                                                  endpoint, **args)
