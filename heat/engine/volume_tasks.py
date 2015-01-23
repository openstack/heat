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

from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.engine import resource

LOG = logging.getLogger(__name__)


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
