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

logger = logging.getLogger(__name__)


from heat.common import heat_keystoneclient as hkc
from novaclient import client as novaclient
try:
    from swiftclient import client as swiftclient
except ImportError:
    swiftclient = None
    logger.info('swiftclient not available')
try:
    from neutronclient.v2_0 import client as neutronclient
except ImportError:
    neutronclient = None
    logger.info('neutronclient not available')
try:
    from cinderclient import client as cinderclient
except ImportError:
    cinderclient = None
    logger.info('cinderclient not available')

try:
    from ceilometerclient.v2 import client as ceilometerclient
except ImportError:
    ceilometerclient = None
    logger.info('ceilometerclient not available')


cloud_opts = [
    cfg.StrOpt('cloud_backend',
               default=None,
               help="Cloud module to use as a backend. Defaults to OpenStack.")
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
            logger.error("Nova connection failed, no auth_token!")
            return None

        args = {
            'project_id': con.tenant,
            'auth_url': con.auth_url,
            'service_type': service_type,
            'username': None,
            'api_key': None
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
            logger.error("Swift connection failed, no auth_token!")
            return None

        args = {
            'auth_version': '2.0',
            'tenant_name': con.tenant,
            'user': con.username,
            'key': None,
            'authurl': None,
            'preauthtoken': self.auth_token,
            'preauthurl': self.url_for(service_type='object-store')
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
            logger.error("Neutron connection failed, no auth_token!")
            return None

        args = {
            'auth_url': con.auth_url,
            'service_type': 'network',
            'token': self.auth_token,
            'endpoint_url': self.url_for(service_type='network')
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
            logger.error("Cinder connection failed, no auth_token!")
            return None

        args = {
            'service_type': 'volume',
            'auth_url': con.auth_url,
            'project_id': con.tenant,
            'username': None,
            'api_key': None
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
            logger.error("Ceilometer connection failed, no auth_token!")
            return None
        con = self.context
        args = {
            'auth_url': con.auth_url,
            'service_type': 'metering',
            'project_id': con.tenant,
            'token': lambda: self.auth_token,
            'endpoint': self.url_for(service_type='metering'),
        }

        client = ceilometerclient.Client(**args)

        self._ceilometer = client
        return self._ceilometer


if cfg.CONF.cloud_backend:
    cloud_backend_module = importutils.import_module(cfg.CONF.cloud_backend)
    Clients = cloud_backend_module.Clients
else:
    Clients = OpenStackClients

logger.debug('Using backend %s' % Clients)
