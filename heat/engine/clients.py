# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from heat.openstack.common import importutils
from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

logger = logging.getLogger(__name__)


from heat.common import heat_keystoneclient as hkc
from novaclient import client as novaclient
from novaclient import shell as novashell
try:
    from swiftclient import client as swiftclient
except ImportError:
    swiftclient = None
    logger.info(_('swiftclient not available'))
try:
    from neutronclient.v2_0 import client as neutronclient
except ImportError:
    neutronclient = None
    logger.info(_('neutronclient not available'))
try:
    from cinderclient import client as cinderclient
except ImportError:
    cinderclient = None
    logger.info(_('cinderclient not available'))

try:
    from ceilometerclient.v2 import client as ceilometerclient
except ImportError:
    ceilometerclient = None
    logger.info(_('ceilometerclient not available'))

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
        self._nova = {}
        self._keystone = None
        self._swift = None
        self._neutron = None
        self._cinder = None
        self._ceilometer = None

    @property
    def auth_token(self):
        # if there is no auth token in the context
        # attempt to get one using the context username and password
        return self.context.auth_token or self.keystone().auth_token

    def keystone(self):
        if self._keystone:
            return self._keystone

        self._keystone = hkc.KeystoneClient(self.context)
        return self._keystone

    def url_for(self, **kwargs):
        return self.keystone().url_for(**kwargs)

    def nova(self, service_type='compute'):
        if service_type in self._nova:
            return self._nova[service_type]

        con = self.context
        if self.auth_token is None:
            logger.error(_("Nova connection failed, no auth_token!"))
            return None

        computeshell = novashell.OpenStackComputeShell()
        extensions = computeshell._discover_extensions("1.1")

        args = {
            'project_id': con.tenant,
            'auth_url': con.auth_url,
            'service_type': service_type,
            'username': None,
            'api_key': None,
            'extensions': extensions,
            'cacert': self._get_client_option('nova', 'ca_file'),
            'insecure': self._get_client_option('nova', 'insecure')
        }

        client = novaclient.Client(1.1, **args)

        management_url = self.url_for(service_type=service_type)
        client.client.auth_token = self.auth_token
        client.client.management_url = management_url

        self._nova[service_type] = client
        return client

    def swift(self):
        if swiftclient is None:
            return None
        if self._swift:
            return self._swift

        con = self.context
        if self.auth_token is None:
            logger.error(_("Swift connection failed, no auth_token!"))
            return None

        args = {
            'auth_version': '2.0',
            'tenant_name': con.tenant,
            'user': con.username,
            'key': None,
            'authurl': None,
            'preauthtoken': self.auth_token,
            'preauthurl': self.url_for(service_type='object-store'),
            'cacert': self._get_client_option('swift', 'ca_file'),
            'insecure': self._get_client_option('swift', 'insecure')
        }
        self._swift = swiftclient.Connection(**args)
        return self._swift

    def neutron(self):
        if neutronclient is None:
            return None
        if self._neutron:
            return self._neutron

        con = self.context
        if self.auth_token is None:
            logger.error(_("Neutron connection failed, no auth_token!"))
            return None

        args = {
            'auth_url': con.auth_url,
            'service_type': 'network',
            'token': self.auth_token,
            'endpoint_url': self.url_for(service_type='network'),
            'ca_cert': self._get_client_option('neutron', 'ca_file'),
            'insecure': self._get_client_option('neutron', 'insecure')
        }

        self._neutron = neutronclient.Client(**args)

        return self._neutron

    def cinder(self):
        if cinderclient is None:
            return self.nova('volume')
        if self._cinder:
            return self._cinder

        con = self.context
        if self.auth_token is None:
            logger.error(_("Cinder connection failed, no auth_token!"))
            return None

        args = {
            'service_type': 'volume',
            'auth_url': con.auth_url,
            'project_id': con.tenant,
            'username': None,
            'api_key': None,
            'cacert': self._get_client_option('cinder', 'ca_file'),
            'insecure': self._get_client_option('cinder', 'insecure')
        }

        self._cinder = cinderclient.Client('1', **args)
        management_url = self.url_for(service_type='volume')
        self._cinder.client.auth_token = self.auth_token
        self._cinder.client.management_url = management_url

        return self._cinder

    def ceilometer(self):
        if ceilometerclient is None:
            return None
        if self._ceilometer:
            return self._ceilometer

        if self.auth_token is None:
            logger.error(_("Ceilometer connection failed, no auth_token!"))
            return None
        con = self.context
        args = {
            'auth_url': con.auth_url,
            'service_type': 'metering',
            'project_id': con.tenant,
            'token': lambda: self.auth_token,
            'endpoint': self.url_for(service_type='metering'),
            'ca_file': self._get_client_option('ceilometer', 'ca_file'),
            'cert_file': self._get_client_option('ceilometer', 'cert_file'),
            'key_file': self._get_client_option('ceilometer', 'key_file'),
            'insecure': self._get_client_option('ceilometer', 'insecure')
        }

        client = ceilometerclient.Client(**args)

        self._ceilometer = client
        return self._ceilometer

    def _get_client_option(self, client, option):
        try:
            group_name = 'clients_' + client
            cfg.CONF.import_opt(option, 'heat.common.config',
                                group=group_name)
            return getattr(getattr(cfg.CONF, group_name), option)
        except (cfg.NoSuchGroupError, cfg.NoSuchOptError):
            cfg.CONF.import_opt(option, 'heat.common.config', group='clients')
            return getattr(cfg.CONF.clients, option)


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
