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

from cinderclient import client as cc
from cinderclient import exceptions
from keystoneauth1 import exceptions as ks_exceptions
from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine.clients import os as os_client
from heat.engine import constraints


LOG = logging.getLogger(__name__)

CLIENT_NAME = 'cinder'


class CinderClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [VOLUME_V2, VOLUME_V3] = ['volumev2', 'volumev3']

    def get_volume_api_version(self):
        '''Returns the most recent API version.'''
        self.interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        try:
            self.context.keystone_session.get_endpoint(
                service_type=self.VOLUME_V3,
                interface=self.interface)
            self.service_type = self.VOLUME_V3
            self.client_version = '3'
        except ks_exceptions.EndpointNotFound:
            try:
                self.context.keystone_session.get_endpoint(
                    service_type=self.VOLUME_V2,
                    interface=self.interface)
                self.service_type = self.VOLUME_V2
                self.client_version = '2'
            except ks_exceptions.EndpointNotFound:
                raise exception.Error(_('No volume service available.'))

    def _create(self):
        self.get_volume_api_version()
        extensions = cc.discover_extensions(self.client_version)
        args = {
            'session': self.context.keystone_session,
            'extensions': extensions,
            'interface': self.interface,
            'service_type': self.service_type,
            'region_name': self._get_region_name(),
            'http_log_debug': self._get_client_option(CLIENT_NAME,
                                                      'http_log_debug')
        }

        client = cc.Client(self.client_version, **args)
        return client

    @os_client.MEMOIZE_EXTENSIONS
    def _list_extensions(self):
        extensions = self.client().list_extensions.show_all()
        return set(extension.alias for extension in extensions)

    def has_extension(self, alias):
        """Check if specific extension is present."""
        return alias in self._list_extensions()

    def get_volume(self, volume):
        try:
            return self.client().volumes.get(volume)
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='Volume', name=volume)

    def get_volume_snapshot(self, snapshot):
        try:
            return self.client().volume_snapshots.get(snapshot)
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='VolumeSnapshot',
                                           name=snapshot)

    def get_volume_backup(self, backup):
        try:
            return self.client().backups.get(backup)
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='Volume backup',
                                           name=backup)

    def get_volume_type(self, volume_type):
        vt_id = None
        volume_type_list = self.client().volume_types.list()
        for vt in volume_type_list:
            if volume_type in [vt.name, vt.id]:
                vt_id = vt.id
                break
        if vt_id is None:
            raise exception.EntityNotFound(entity='VolumeType',
                                           name=volume_type)

        return vt_id

    def get_qos_specs(self, qos_specs):
        try:
            qos = self.client().qos_specs.get(qos_specs)
        except exceptions.NotFound:
            qos = self.client().qos_specs.find(name=qos_specs)
        return qos.id

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.OverLimit)

    def is_conflict(self, ex):
        return (isinstance(ex, exceptions.ClientException) and
                ex.code == 409)

    def check_detach_volume_complete(self, vol_id, server_id=None):
        try:
            vol = self.client().volumes.get(vol_id)
        except Exception as ex:
            self.ignore_not_found(ex)
            return True

        server_ids = [
            a['server_id'] for a in vol.attachments if 'server_id' in a]
        if server_id and server_id not in server_ids:
            return True

        if vol.status in ('in-use', 'detaching', 'reserved'):
            LOG.debug('%s - volume still in use', vol_id)
            return False

        LOG.debug('Volume %(id)s - status: %(status)s', {
            'id': vol.id, 'status': vol.status})

        if vol.status not in ('available', 'deleting'):
            LOG.debug("Detachment failed - volume %(vol)s "
                      "is in %(status)s status",
                      {"vol": vol.id, "status": vol.status})
            raise exception.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume detachment failed'))
        else:
            return True

    def check_attach_volume_complete(self, vol_id):
        vol = self.client().volumes.get(vol_id)
        if vol.status in ('available', 'attaching', 'reserved'):
            LOG.debug("Volume %(id)s is being attached - "
                      "volume status: %(status)s",
                      {'id': vol_id, 'status': vol.status})
            return False

        if vol.status != 'in-use':
            LOG.debug("Attachment failed - volume %(vol)s is "
                      "in %(status)s status",
                      {"vol": vol_id, "status": vol.status})
            raise exception.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume attachment failed'))

        LOG.info('Attaching volume %(id)s complete', {'id': vol_id})
        return True


class BaseCinderConstraint(constraints.BaseCustomConstraint):

    resource_client_name = CLIENT_NAME


class VolumeConstraint(BaseCinderConstraint):

    resource_getter_name = 'get_volume'


class VolumeSnapshotConstraint(BaseCinderConstraint):

    resource_getter_name = 'get_volume_snapshot'


class VolumeTypeConstraint(BaseCinderConstraint):

    resource_getter_name = 'get_volume_type'


class VolumeBackupConstraint(BaseCinderConstraint):

    resource_getter_name = 'get_volume_backup'


class QoSSpecsConstraint(BaseCinderConstraint):

    expected_exceptions = (exceptions.NotFound,)

    resource_getter_name = 'get_qos_specs'
