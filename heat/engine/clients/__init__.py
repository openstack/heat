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
from oslo.config import cfg
from stevedore import extension
from troveclient import client as troveclient
import warnings

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
        self._client_plugins = {}

    def client_plugin(self, name):
        global _mgr
        if name in self._client_plugins:
            return self._client_plugins[name]
        if _mgr and name in _mgr.names():
            client_plugin = _mgr[name].plugin(self)
            self._client_plugins[name] = client_plugin
            return client_plugin

    def client(self, name):
        client_plugin = self.client_plugin(name)
        if client_plugin:
            return client_plugin.client()

        if name in self._clients:
            return self._clients[name]
        # call the local method _<name>() if a real client plugin
        # doesn't exist
        method_name = '_%s' % name
        if callable(getattr(self, method_name, None)):
            client = getattr(self, method_name)()
            self._clients[name] = client
            return client
        LOG.warn(_('Requested client "%s" not found') % name)

    @property
    def auth_token(self):
        # Always use the auth_token from the keystone() client, as
        # this may be refreshed if the context contains credentials
        # which allow reissuing of a new token before the context
        # auth_token expiry (e.g trust_id or username/password)
        return self.client('keystone').auth_token

    def keystone(self):
        warnings.warn('keystone() is deprecated. '
                      'Replace with calls to client("keystone")')
        return self.client('keystone')

    def _keystone(self):
        return hkc.KeystoneClient(self.context)

    def url_for(self, **kwargs):
        return self.client('keystone').url_for(**kwargs)

    def nova(self):
        warnings.warn('nova() is deprecated. '
                      'Replace with calls to client("nova")')
        return self.client('nova')

    def swift(self):
        warnings.warn('swift() is deprecated. '
                      'Replace with calls to client("swift")')
        return self.client('swift')

    def glance(self):
        warnings.warn('glance() is deprecated. '
                      'Replace with calls to client("glance")')
        return self.client('glance')

    def _glance(self):

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

        return glanceclient.Client('1', endpoint, **args)

    def neutron(self):
        warnings.warn('neutron() is deprecated. '
                      'Replace with calls to client("neutron")')
        return self.client('neutron')

    def _neutron(self):

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

        return neutronclient.Client(**args)

    def cinder(self):
        warnings.warn('cinder() is deprecated. '
                      'Replace with calls to client("cinder")')
        return self.client('cinder')

    def _cinder(self):

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

        client = cinderclient.Client('1', **args)
        management_url = self.url_for(service_type='volume',
                                      endpoint_type=endpoint_type)
        client.client.auth_token = self.auth_token
        client.client.management_url = management_url

        return client

    def trove(self):
        warnings.warn('trove() is deprecated. '
                      'Replace with calls to client("trove")')
        return self.client('trove')

    def _trove(self):

        con = self.context
        endpoint_type = self._get_client_option('trove', 'endpoint_type')
        args = {
            'service_type': 'database',
            'auth_url': con.auth_url,
            'proxy_token': con.auth_token,
            'username': None,
            'password': None,
            'cacert': self._get_client_option('trove', 'ca_file'),
            'insecure': self._get_client_option('trove', 'insecure'),
            'endpoint_type': endpoint_type
        }

        client = troveclient.Client('1.0', **args)
        management_url = self.url_for(service_type='database',
                                      endpoint_type=endpoint_type)
        client.client.auth_token = con.auth_token
        client.client.management_url = management_url

        return client

    def ceilometer(self):
        warnings.warn('ceilometer() is deprecated. '
                      'Replace with calls to client("ceilometer")')
        return self.client('ceilometer')

    def _ceilometer(self):

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

        return ceilometerclient.Client('2', endpoint, **args)

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
        warnings.warn('heat() is deprecated. '
                      'Replace with calls to client("heat")')
        return self.client('heat')

    def _heat(self):

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
        return heatclient.Client('1', endpoint, **args)


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


_mgr = None


def has_client(name):
    return _mgr and name in _mgr


def initialise():
    global _mgr
    if _mgr:
        return

    _mgr = extension.ExtensionManager(
        namespace='heat.clients',
        invoke_on_load=False,
        verify_requirements=True)
