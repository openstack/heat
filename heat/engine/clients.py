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

import eventlet
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
    from quantumclient.v2_0 import client as quantumclient
except ImportError:
    quantumclient = None
    logger.info('quantumclient not available')
try:
    from cinderclient import client as cinderclient
except ImportError:
    cinderclient = None
    logger.info('cinderclient not available')


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
        self._quantum = None
        self._cinder = None

    def keystone(self):
        if self._keystone:
            return self._keystone

        self._keystone = hkc.KeystoneClient(self.context)
        return self._keystone

    def url_for(self, **kwargs):
        return self.keystone().client.service_catalog.url_for(**kwargs)

    def nova(self, service_type='compute'):
        if service_type in self._nova:
            return self._nova[service_type]

        con = self.context
        args = {
            'project_id': con.tenant,
            'auth_url': con.auth_url,
            'service_type': service_type,
        }

        if con.password is not None:
            args['username'] = con.username
            args['api_key'] = con.password
        elif con.auth_token is not None:
            args['username'] = None
            args['api_key'] = None
        else:
            logger.error("Nova connection failed, no password or auth_token!")
            return None

        client = novaclient.Client(1.1, **args)

        if con.password is None and con.auth_token is not None:
            management_url = self.url_for(service_type=service_type)
            client.client.auth_token = con.auth_token
            client.client.management_url = management_url
        return client

    def swift(self):
        if swiftclient is None:
            return None
        if self._swift:
            return self._swift

        con = self.context
        args = {
            'auth_version': '2.0',
            'tenant_name': con.tenant,
            'user': con.username
        }

        if con.password is not None:
            args['key'] = con.password
            args['authurl'] = con.auth_url
        elif con.auth_token is not None:
            args['key'] = None
            args['authurl'] = None
            args['preauthtoken'] = con.auth_token
            args['preauthurl'] = self.url_for(service_type='object-store')
        else:
            logger.error("Swift connection failed, no password or " +
                         "auth_token!")
            return None
        self._swift = swiftclient.Connection(**args)
        return self._swift

    def quantum(self):
        if quantumclient is None:
            return None
        if self._quantum:
            logger.debug('using existing _quantum')
            return self._quantum

        con = self.context
        args = {
            'auth_url': con.auth_url,
            'service_type': 'network',
        }

        if con.password is not None:
            args['username'] = con.username
            args['password'] = con.password
            args['tenant_name'] = con.tenant
        elif con.auth_token is not None:
            args['token'] = con.auth_token
            args['endpoint_url'] = self.url_for(service_type='network')
        else:
            logger.error("Quantum connection failed, "
                         "no password or auth_token!")
            return None
        logger.debug('quantum args %s', args)

        self._quantum = quantumclient.Client(**args)

        return self._quantum

    def cinder(self):
        if cinderclient is None:
            return self.nova('volume')
        if self._cinder:
            return self._cinder

        con = self.context
        args = {
            'service_type': 'volume',
            'auth_url': con.auth_url,
            'project_id': con.tenant
        }

        if con.password is not None:
            args['username'] = con.username
            args['api_key'] = con.password
        elif con.auth_token is not None:
            args['username'] = None
            args['api_key'] = None
        else:
            logger.error("Cinder connection failed, "
                         "no password or auth_token!")
            return None
        logger.debug('cinder args %s', args)

        self._cinder = cinderclient.Client('1', **args)
        if con.password is None and con.auth_token is not None:
            management_url = self.url_for(service_type='volume')
            self._cinder.client.auth_token = con.auth_token
            self._cinder.client.management_url = management_url

        return self._cinder

    def detach_volume_from_instance(self, server_id, volume_id):
        logger.info('VolumeAttachment un-attaching %s %s' %
                    (server_id, volume_id))

        try:
            vol = self.cinder().volumes.get(volume_id)
        except cinderclient.exceptions.NotFound:
            logger.warning('Volume %s - not found' %
                          (volume_id))
            return
        try:
            self.nova().volumes.delete_server_volume(server_id,
                                                     volume_id)
        except novaclient.exceptions.NotFound:
            logger.warning('Deleting VolumeAttachment %s %s - not found' %
                          (server_id, volume_id))
        try:
            logger.info('un-attaching %s, status %s' % (volume_id, vol.status))
            while vol.status == 'in-use':
                logger.info('trying to un-attach %s, but still %s' %
                            (volume_id, vol.status))
                eventlet.sleep(1)
                try:
                    self.nova().volumes.delete_server_volume(
                        server_id,
                        volume_id)
                except Exception:
                    pass
                vol.get()
            logger.info('volume status of %s now %s' % (volume_id, vol.status))
        except cinderclient.exceptions.NotFound:
            logger.warning('Volume %s - not found' %
                          (volume_id))


if cfg.CONF.cloud_backend:
    cloud_backend_module = importutils.import_module(cfg.CONF.cloud_backend)
    Clients = cloud_backend_module.Clients
else:
    Clients = OpenStackClients

logger.debug('Using backend %s' % Clients)
