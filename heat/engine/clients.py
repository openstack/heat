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

from ceilometerclient import client as ceilometerclient
from cinderclient import client as cinderclient
from glanceclient import client as glanceclient
from heatclient import client as heatclient
from neutronclient.v2_0 import client as neutronclient
from novaclient import client as novaclient
from novaclient import shell as novashell
from oslo.config import cfg
from swiftclient import client as swiftclient
from troveclient import client as troveclient

from heat.common import heat_keystoneclient as hkc
from heat.openstack.common.gettextutils import _
from heat.openstack.common import importutils
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


_default_backend = "heat.engine.clients.OpenStackClients"

cloud_opts = [
    cfg.StrOpt('cloud_backend',
               default=_default_backend,
               help="Fully qualified class name to use as a client backend.")
]
cfg.CONF.register_opts(cloud_opts)


class OpenStackClients(object):
    '''
    Convenience class to create and cache client instances.
    '''
    def __init__(self, context):
        self.context = context
        self._clients = {}

    @property
    def auth_token(self):
        # Always use the auth_token from the keystone() client, as
        # this may be refreshed if the context contains credentials
        # which allow reissuing of a new token before the context
        # auth_token expiry (e.g trust_id or username/password)
        return self.keystone().auth_token

    def keystone(self):
        if 'keystone' in self._clients:
            return self._clients['keystone']

        self._clients['keystone'] = hkc.KeystoneClient(self.context)
        return self._clients['keystone']

    def url_for(self, **kwargs):
        return self.keystone().url_for(**kwargs)

    def nova(self):
        if 'nova' in self._clients:
            return self._clients['nova']

        con = self.context
        computeshell = novashell.OpenStackComputeShell()
        extensions = computeshell._discover_extensions("1.1")

        endpoint_type = self._get_client_option('nova', 'endpoint_type')
        args = {
            'project_id': con.tenant,
            'auth_url': con.auth_url,
            'service_type': 'compute',
            'username': None,
            'api_key': None,
            'extensions': extensions,
            'endpoint_type': endpoint_type,
            'http_log_debug': self._get_client_option('nova',
                                                      'http_log_debug'),
            'cacert': self._get_client_option('nova', 'ca_file'),
            'insecure': self._get_client_option('nova', 'insecure')
        }

        client = novaclient.Client(1.1, **args)

        management_url = self.url_for(service_type='compute',
                                      endpoint_type=endpoint_type)
        client.client.auth_token = self.auth_token
        client.client.management_url = management_url

        self._clients['nova'] = client
        return client

    def swift(self):
        if 'swift' in self._clients:
            return self._clients['swift']

        con = self.context
        endpoint_type = self._get_client_option('swift', 'endpoint_type')
        args = {
            'auth_version': '2.0',
            'tenant_name': con.tenant,
            'user': con.username,
            'key': None,
            'authurl': None,
            'preauthtoken': self.auth_token,
            'preauthurl': self.url_for(service_type='object-store',
                                       endpoint_type=endpoint_type),
            'os_options': {'endpoint_type': endpoint_type},
            'cacert': self._get_client_option('swift', 'ca_file'),
            'insecure': self._get_client_option('swift', 'insecure')
        }
        self._clients['swift'] = swiftclient.Connection(**args)
        return self._clients['swift']

    def glance(self):
        if 'glance' in self._clients:
            return self._clients['glance']

        con = self.context
        endpoint_type = self._get_client_option('glance', 'endpoint_type')
        endpoint = self.url_for(service_type='image',
                                endpoint_type=endpoint_type)
        args = {
            'auth_url': con.auth_url,
            'service_type': 'image',
            'project_id': con.tenant,
            'token': self.auth_token,
            'endpoint_type': endpoint_type,
            'ca_file': self._get_client_option('glance', 'ca_file'),
            'cert_file': self._get_client_option('glance', 'cert_file'),
            'key_file': self._get_client_option('glance', 'key_file'),
            'insecure': self._get_client_option('glance', 'insecure')
        }

        self._clients['glance'] = glanceclient.Client('1', endpoint, **args)
        return self._clients['glance']

    def neutron(self):
        if 'neutron' in self._clients:
            return self._clients['neutron']

        con = self.context
        if self.auth_token is None:
            LOG.error(_("Neutron connection failed, no auth_token!"))
            return None

        endpoint_type = self._get_client_option('neutron', 'endpoint_type')
        args = {
            'auth_url': con.auth_url,
            'service_type': 'network',
            'token': self.auth_token,
            'endpoint_url': self.url_for(service_type='network',
                                         endpoint_type=endpoint_type),
            'endpoint_type': endpoint_type,
            'ca_cert': self._get_client_option('neutron', 'ca_file'),
            'insecure': self._get_client_option('neutron', 'insecure')
        }

        self._clients['neutron'] = neutronclient.Client(**args)

        return self._clients['neutron']

    def cinder(self):
        if 'cinder' in self._clients:
            return self._clients['cinder']

        con = self.context
        endpoint_type = self._get_client_option('cinder', 'endpoint_type')
        args = {
            'service_type': 'volume',
            'auth_url': con.auth_url,
            'project_id': con.tenant,
            'username': None,
            'api_key': None,
            'endpoint_type': endpoint_type,
            'cacert': self._get_client_option('cinder', 'ca_file'),
            'insecure': self._get_client_option('cinder', 'insecure')
        }

        self._clients['cinder'] = cinderclient.Client('1', **args)
        management_url = self.url_for(service_type='volume',
                                      endpoint_type=endpoint_type)
        self._clients['cinder'].client.auth_token = self.auth_token
        self._clients['cinder'].client.management_url = management_url

        return self._clients['cinder']

    def trove(self, service_type="database"):
        if 'trove' in self._clients:
            return self._clients['trove']

        con = self.context
        endpoint_type = self._get_client_option('trove', 'endpoint_type')
        args = {
            'service_type': service_type,
            'auth_url': con.auth_url,
            'proxy_token': con.auth_token,
            'username': None,
            'password': None,
            'cacert': self._get_client_option('trove', 'ca_file'),
            'insecure': self._get_client_option('trove', 'insecure'),
            'endpoint_type': endpoint_type
        }

        self._clients['trove'] = troveclient.Client('1.0', **args)
        management_url = self.url_for(service_type=service_type,
                                      endpoint_type=endpoint_type)
        self._clients['trove'].client.auth_token = con.auth_token
        self._clients['trove'].client.management_url = management_url

        return self._clients['trove']

    def ceilometer(self):
        if 'ceilometer' in self._clients:
            return self._clients['ceilometer']

        con = self.context
        endpoint_type = self._get_client_option('ceilometer', 'endpoint_type')
        endpoint = self.url_for(service_type='metering',
                                endpoint_type=endpoint_type)
        args = {
            'auth_url': con.auth_url,
            'service_type': 'metering',
            'project_id': con.tenant,
            'token': lambda: self.auth_token,
            'endpoint_type': endpoint_type,
            'ca_file': self._get_client_option('ceilometer', 'ca_file'),
            'cert_file': self._get_client_option('ceilometer', 'cert_file'),
            'key_file': self._get_client_option('ceilometer', 'key_file'),
            'insecure': self._get_client_option('ceilometer', 'insecure')
        }

        client = ceilometerclient.Client('2', endpoint, **args)

        self._clients['ceilometer'] = client
        return self._clients['ceilometer']

    def _get_client_option(self, client, option):
        try:
            group_name = 'clients_' + client
            cfg.CONF.import_opt(option, 'heat.common.config',
                                group=group_name)
            return getattr(getattr(cfg.CONF, group_name), option)
        except (cfg.NoSuchGroupError, cfg.NoSuchOptError):
            cfg.CONF.import_opt(option, 'heat.common.config', group='clients')
            return getattr(cfg.CONF.clients, option)

    def _get_heat_url(self):
        heat_url = self._get_client_option('heat', 'url')
        if heat_url:
            tenant_id = self.context.tenant_id
            heat_url = heat_url % {'tenant_id': tenant_id}
        return heat_url

    def heat(self):
        if 'heat' in self._clients:
            return self._clients['heat']

        con = self.context
        endpoint_type = self._get_client_option('heat', 'endpoint_type')
        args = {
            'auth_url': con.auth_url,
            'token': self.auth_token,
            'username': None,
            'password': None,
            'ca_file': self._get_client_option('heat', 'ca_file'),
            'cert_file': self._get_client_option('heat', 'cert_file'),
            'key_file': self._get_client_option('heat', 'key_file'),
            'insecure': self._get_client_option('heat', 'insecure')
        }

        endpoint = self._get_heat_url()
        if not endpoint:
            endpoint = self.url_for(service_type='orchestration',
                                    endpoint_type=endpoint_type)
        self._clients['heat'] = heatclient.Client('1', endpoint, **args)

        return self._clients['heat']


class ClientBackend(object):
    '''Delay choosing the backend client module until the client's class needs
    to be initialized.
    '''
    def __new__(cls, context):
        if cfg.CONF.cloud_backend == _default_backend:
            return OpenStackClients(context)
        else:
            return importutils.import_object(
                cfg.CONF.cloud_backend,
                context
            )


Clients = ClientBackend
