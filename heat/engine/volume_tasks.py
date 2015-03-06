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

from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine import resource

LOG = logging.getLogger(__name__)


class VolumeExtendTask(object):
    """A task to resize volume using Cinder API."""

    def __init__(self, stack, volume_id, size):
        self.clients = stack.clients
        self.volume_id = volume_id
        self.size = size

    def __str__(self):
        return _("Resizing volume %(vol)s to size %(size)i") % {
            'vol': self.volume_id, 'size': self.size}

    def __repr__(self):
        return "%s(%s +-> %i)" % (type(self).__name__, self.volume_id,
                                  self.size)

    def __call__(self):
        LOG.debug(str(self))

        cinder = self.clients.client('cinder').volumes
        vol = cinder.get(self.volume_id)

        try:
            cinder.extend(self.volume_id, self.size)
        except Exception as ex:
            if self.clients.client_plugin('cinder').is_client_exception(ex):
                raise exception.Error(_(
                    "Failed to extend volume %(vol)s - %(err)s") % {
                        'vol': vol.id, 'err': ex})
            else:
                raise

        yield

        vol = cinder.get(self.volume_id)
        while vol.status == 'extending':
            LOG.debug("Volume %s is being extended" % self.volume_id)
            yield
            vol = cinder.get(self.volume_id)

        if vol.status != 'available':
            LOG.info(_LI("Resize failed: Volume %(vol)s is in %(status)s "
                         "state."), {'vol': vol.id, 'status': vol.status})
            raise resource.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume resize failed'))

        LOG.info(_LI('%s - complete'), str(self))


class VolumeAttachTask(object):
    """A task for attaching a volume to a Nova server."""

    def __init__(self, stack, server_id, volume_id, device):
        """
        Initialise with the stack (for obtaining the clients), ID of the
        server and volume, and the device name on the server.
        """
        self.clients = stack.clients
        self.server_id = server_id
        self.volume_id = volume_id
        self.device = device
        self.attachment_id = None

    def __str__(self):
        """Return a human-readable string description of the task."""
        return 'Attaching Volume %s to Instance %s as %s' % (self.volume_id,
                                                             self.server_id,
                                                             self.device)

    def __repr__(self):
        """Return a brief string description of the task."""
        return '%s(%s -> %s [%s])' % (type(self).__name__,
                                      self.volume_id,
                                      self.server_id,
                                      self.device)

    def __call__(self):
        """Return a co-routine which runs the task."""
        LOG.debug(str(self))

        va = self.clients.client('nova').volumes.create_server_volume(
            server_id=self.server_id,
            volume_id=self.volume_id,
            device=self.device)
        self.attachment_id = va.id
        yield

        cinder = self.clients.client('cinder')

        vol = cinder.volumes.get(self.volume_id)
        while vol.status == 'available' or vol.status == 'attaching':
            LOG.debug('%(name)s - volume status: %(status)s'
                      % {'name': str(self), 'status': vol.status})
            yield
            vol = cinder.volumes.get(self.volume_id)

        if vol.status != 'in-use':
            LOG.info(_LI("Attachment failed - volume %(vol)s "
                         "is in %(status)s status"),
                     {"vol": vol.id,
                      "status": vol.status})
            raise resource.ResourceUnknownStatus(
                resource_status=vol.status,
                result=_('Volume attachment failed'))

        LOG.info(_LI('%s - complete'), str(self))


class VolumeDetachTask(object):
    """A task for detaching a volume from a Nova server."""

    def __init__(self, stack, server_id, attachment_id):
        """
        Initialise with the stack (for obtaining the clients), and the IDs of
        the server and volume.
        """
        self.clients = stack.clients
        self.server_id = server_id
        self.attachment_id = attachment_id

    def __str__(self):
        """Return a human-readable string description of the task."""
        return _('Removing attachment %(att)s from Instance %(srv)s') % {
            'att': self.attachment_id, 'srv': self.server_id}

    def __repr__(self):
        """Return a brief string description of the task."""
        return '%s(%s -/> %s)' % (type(self).__name__,
                                  self.attachment_id,
                                  self.server_id)

    def __call__(self):
        """Return a co-routine which runs the task."""
        LOG.debug(str(self))

        nova_plugin = self.clients.client_plugin('nova')
        cinder_plugin = self.clients.client_plugin('cinder')
        server_api = self.clients.client('nova').volumes
        cinder = self.clients.client('cinder')
        # get reference to the volume while it is attached
        try:
            nova_vol = server_api.get_server_volume(self.server_id,
                                                    self.attachment_id)
            vol = cinder.volumes.get(nova_vol.id)
        except Exception as ex:
            if (cinder_plugin.is_not_found(ex) or
                    nova_plugin.is_not_found(ex) or
                    nova_plugin.is_bad_request(ex)):
                return
            else:
                raise

        if vol.status == 'deleting':
            return

        # detach the volume using volume_attachment
        try:
            server_api.delete_server_volume(self.server_id, self.attachment_id)
        except Exception as ex:
            if nova_plugin.is_not_found(ex) or nova_plugin.is_bad_request(ex):
                pass
            else:
                raise

        yield

        try:
            while vol.status in ('in-use', 'detaching'):
                LOG.debug('%s - volume still in use' % str(self))
                yield
                vol = cinder.volumes.get(nova_vol.id)

            LOG.info(_LI('%(name)s - status: %(status)s'),
                     {'name': str(self), 'status': vol.status})
            if vol.status not in ['available', 'deleting']:
                LOG.info(_LI("Detachment failed - volume %(vol)s "
                             "is in %(status)s status"),
                         {"vol": vol.id,
                          "status": vol.status})
                raise resource.ResourceUnknownStatus(
                    resource_status=vol.status,
                    result=_('Volume detachment failed'))

        except Exception as ex:
            cinder_plugin.ignore_not_found(ex)

        # The next check is needed for immediate reattachment when updating:
        # there might be some time between cinder marking volume as 'available'
        # and nova removing attachment from its own objects, so we
        # check that nova already knows that the volume is detached
        def server_has_attachment(server_id, attachment_id):
            try:
                server_api.get_server_volume(server_id, attachment_id)
            except Exception as ex:
                nova_plugin.ignore_not_found(ex)
                return False
            return True

        while server_has_attachment(self.server_id, self.attachment_id):
            LOG.info(_LI("Server %(srv)s still has attachment %(att)s."),
                     {'att': self.attachment_id, 'srv': self.server_id})
            yield

        LOG.info(_LI("Volume %(vol)s is detached from server %(srv)s"),
                 {'vol': vol.id, 'srv': self.server_id})
