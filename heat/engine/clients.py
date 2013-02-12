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

from heat.openstack.common import cfg
from heat.openstack.common import importutils
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


from heat.common import exception
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
    from cinderclient.v1 import client as cinderclient
    from cinderclient import exceptions as cinder_exceptions
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
            args['username'] = con.service_user
            args['api_key'] = con.service_password
            args['project_id'] = con.service_tenant
            args['proxy_token'] = con.auth_token
            args['proxy_tenant_id'] = con.tenant_id
        else:
            logger.error("Nova connection failed, no password or auth_token!")
            return None

        client = None
        try:
            # Workaround for issues with python-keyring, need no_cache=True
            # ref https://bugs.launchpad.net/python-novaclient/+bug/1020238
            # TODO(shardy): May be able to remove when the bug above is fixed
            client = novaclient.Client(1.1, no_cache=True, **args)
            client.authenticate()
            self._nova[service_type] = client
        except TypeError:
            # for compatibility with essex, which doesn't have no_cache=True
            # TODO(shardy): remove when we no longer support essex
            client = novaclient.Client(1.1, **args)
            client.authenticate()
            self._nova[service_type] = client

        return client

    def swift(self):
        if swiftclient is None:
            return None
        if self._swift:
            return self._swift

        con = self.context
        args = {
            'auth_version': '2'
        }

        if con.password is not None:
            args['user'] = con.username
            args['key'] = con.password
            args['authurl'] = con.auth_url
            args['tenant_name'] = con.tenant
        elif con.auth_token is not None:
            args['user'] = None
            args['key'] = None
            args['authurl'] = None
            args['preauthtoken'] = con.auth_token
            # Lookup endpoint for object-store service type
            service_type = 'object-store'
            endpoints = self.keystone().service_catalog.get_endpoints(
                service_type=service_type)
            if len(endpoints[service_type]) == 1:
                args['preauthurl'] = endpoints[service_type][0]['publicURL']
            else:
                logger.error("No endpoint found for %s service type" %
                             service_type)
                return None
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
            args['username'] = con.service_user
            args['password'] = con.service_password
            args['tenant_name'] = con.service_tenant
            args['token'] = con.auth_token
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
            'project_id': con.tenant,
            'auth_url': con.auth_url,
            'service_type': 'volume',
        }

        if con.password is not None:
            args['username'] = con.username
            args['api_key'] = con.password
        elif con.auth_token is not None:
            args['username'] = con.service_user
            args['api_key'] = con.service_password
            args['project_id'] = con.service_tenant
            args['proxy_token'] = con.auth_token
            args['proxy_token_id'] = con.tenant_id
        else:
            logger.error("Cinder connection failed, "
                         "no password or auth_token!")
            return None
        logger.debug('cinder args %s', args)

        self._cinder = cinderclient.Client(**args)

        return self._cinder

    def attach_volume_to_instance(self, server_id, volume_id, device_id):
        logger.warn('Attaching InstanceId %s VolumeId %s Device %s' %
                    (server_id, volume_id, device_id))

        va = self.nova().volumes.create_server_volume(
            server_id=server_id,
            volume_id=volume_id,
            device=device_id)

        vol = self.cinder().volumes.get(va.id)
        while vol.status == 'available' or vol.status == 'attaching':
            eventlet.sleep(1)
            vol.get()
        if vol.status == 'in-use':
            return va.id
        else:
            raise exception.Error(vol.status)

    def detach_volume_from_instance(self, server_id, volume_id):
        logger.info('VolumeAttachment un-attaching %s %s' %
                    (server_id, volume_id))

        try:
            vol = self.cinder().volumes.get(volume_id)
        except cinder_exceptions.NotFound:
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
        except cinder_exceptions.NotFound:
            logger.warning('Volume %s - not found' %
                          (volume_id))


if cfg.CONF.cloud_backend:
    cloud_backend_module = importutils.import_module(cfg.CONF.cloud_backend)
    Clients = cloud_backend_module.Clients
else:
    Clients = OpenStackClients

logger.debug('Using backend %s' % Clients)
