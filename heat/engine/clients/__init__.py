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
from oslo.utils import importutils
from stevedore import extension
import warnings

from heat.common.i18n import _
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
            client_plugin = _mgr[name].plugin(self.context)
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

    def neutron(self):
        warnings.warn('neutron() is deprecated. '
                      'Replace with calls to client("neutron")')
        return self.client('neutron')

    def cinder(self):
        warnings.warn('cinder() is deprecated. '
                      'Replace with calls to client("cinder")')
        return self.client('cinder')

    def trove(self):
        warnings.warn('trove() is deprecated. '
                      'Replace with calls to client("trove")')
        return self.client('trove')

    def ceilometer(self):
        warnings.warn('ceilometer() is deprecated. '
                      'Replace with calls to client("ceilometer")')
        return self.client('ceilometer')

    def heat(self):
        warnings.warn('heat() is deprecated. '
                      'Replace with calls to client("heat")')
        return self.client('heat')


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
    return _mgr and name in _mgr.names()


def initialise():
    global _mgr
    if _mgr:
        return

    _mgr = extension.ExtensionManager(
        namespace='heat.clients',
        invoke_on_load=False,
        verify_requirements=True)
