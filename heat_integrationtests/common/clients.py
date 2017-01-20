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

from ceilometerclient import client as ceilometer_client
from cinderclient import client as cinder_client
from heat.common.i18n import _
from heatclient import client as heat_client
from keystoneauth1 import exceptions as kc_exceptions
from keystoneauth1.identity.generic import password
from keystoneauth1 import session
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client
from swiftclient import client as swift_client


class KeystoneWrapperClient(object):
    """Wrapper object for keystone client

    This wraps keystone client, so we can encpasulate certain
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
            'region_name': region}
        return self.auth_ref.service_catalog.url_for(**kwargs)


class ClientManager(object):
    """Provides access to the official python clients for calling various APIs.

    Manager that provides access to the official python clients for
    calling various OpenStack APIs.
    """

    CINDERCLIENT_VERSION = '2'
    HEATCLIENT_VERSION = '1'
    NOVA_API_VERSION = '2.1'
    CEILOMETER_VERSION = '2'

    def __init__(self, conf, admin_credentials=False):
        self.conf = conf
        self.admin_credentials = admin_credentials

        if self.conf.auth_url.find('/v'):
            self.auth_version = self.conf.auth_url.split('/v')[1]
        else:
            raise ValueError(_('Incorrectly specified auth_url config: no '
                               'version found.'))
        self.insecure = self.conf.disable_ssl_certificate_validation
        self.ca_file = self.conf.ca_file

        self.identity_client = self._get_identity_client()
        self.orchestration_client = self._get_orchestration_client()
        self.compute_client = self._get_compute_client()
        self.network_client = self._get_network_client()
        self.volume_client = self._get_volume_client()
        self.object_client = self._get_object_client()
        self.metering_client = self._get_metering_client()

    def _username(self):
        if self.admin_credentials:
            return self.conf.admin_username
        return self.conf.username

    def _password(self):
        if self.admin_credentials:
            return self.conf.admin_password
        return self.conf.password

    def _tenant_name(self):
        if self.admin_credentials:
            return self.conf.admin_tenant_name
        return self.conf.tenant_name

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
        except kc_exceptions.EndpointNotFound:
            return None
        else:
            return heat_client.Client(
                self.HEATCLIENT_VERSION,
                endpoint,
                token=token,
                username=self._username(),
                password=self._password())

    def _get_identity_client(self):
        user_domain_id = self.conf.user_domain_id
        project_domain_id = self.conf.project_domain_id
        user_domain_name = self.conf.user_domain_name
        project_domain_name = self.conf.project_domain_name
        kwargs = {
            'username': self._username(),
            'password': self._password(),
            'tenant_name': self._tenant_name(),
            'auth_url': self.conf.auth_url
        }
        # keystone v2 can't ignore domain details
        if self.auth_version == '3':
            kwargs.update({
                'user_domain_id': user_domain_id,
                'project_domain_id': project_domain_id,
                'user_domain_name': user_domain_name,
                'project_domain_name': project_domain_name})
        auth = password.Password(**kwargs)
        if self.insecure:
            verify_cert = False
        else:
            verify_cert = self.ca_file or True

        return KeystoneWrapperClient(auth, verify_cert)

    def _get_compute_client(self):

        region = self.conf.region
        # Create our default Nova client to use in testing
        return nova_client.Client(
            self.NOVA_API_VERSION,
            session=self.identity_client.session,
            service_type='compute',
            endpoint_type='publicURL',
            region_name=region,
            os_cache=False,
            insecure=self.insecure,
            cacert=self.ca_file,
            http_log_debug=True)

    def _get_network_client(self):

        return neutron_client.Client(
            session=self.identity_client.session,
            endpoint_type='publicURL',
            insecure=self.insecure,
            ca_cert=self.ca_file)

    def _get_volume_client(self):
        region = self.conf.region
        endpoint_type = 'publicURL'
        return cinder_client.Client(
            self.CINDERCLIENT_VERSION,
            session=self.identity_client.session,
            region_name=region,
            endpoint_type=endpoint_type,
            insecure=self.insecure,
            cacert=self.ca_file,
            http_log_debug=True)

    def _get_object_client(self):
        # swiftclient does not support keystone sessions yet
        args = {
            'auth_version': self.auth_version,
            'tenant_name': self._tenant_name(),
            'user': self._username(),
            'key': self.conf.password,
            'authurl': self.conf.auth_url,
            'os_options': {'endpoint_type': 'publicURL'},
            'insecure': self.insecure,
            'cacert': self.ca_file,
        }
        return swift_client.Connection(**args)

    def _get_metering_client(self):
        try:
            endpoint = self.identity_client.get_endpoint_url('metering',
                                                             self.conf.region)
        except kc_exceptions.EndpointNotFound:
            return None
        else:
            args = {
                'session': self.identity_client.session,
                'insecure': self.insecure,
                'cacert': self.ca_file,
                'region_name': self.conf.region,
                'endpoint_type': 'publicURL',
                'service_type': 'metering',
            }
            return ceilometer_client.Client(self.CEILOMETER_VERSION,
                                            endpoint, **args)
