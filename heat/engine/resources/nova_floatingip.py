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

from heat.engine import clients
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import excutils
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class NovaFloatingIp(resource.Resource):
    PROPERTIES = (POOL,) = ('pool',)

    properties_schema = {
        POOL: properties.Schema(
            properties.Schema.STRING,
            description=_('Allocate a floating IP from a given '
                          'floating IP pool.')
        ),
    }

    attributes_schema = {
        'pool': _('Pool from which floating IP is allocated.'),
        'ip': _('Allocated floating IP address.')
    }

    def __init__(self, name, json_snippet, stack):
        super(NovaFloatingIp, self).__init__(name, json_snippet, stack)
        self._floating_ip = None

    def _get_resource(self):
        if self._floating_ip is None and self.resource_id is not None:
            self._floating_ip = self.nova().floating_ips.get(self.resource_id)

        return self._floating_ip

    def handle_create(self):
        try:
            pool = self.properties.get(self.POOL)
            floating_ip = self.nova().floating_ips.create(pool=pool)
        except clients.novaclient.exceptions.NotFound:
            with excutils.save_and_reraise_exception():
                if pool is None:
                    msg = _('Could not allocate floating IP. Probably there '
                            'is no default floating IP pool is configured.')
                    logger.error(msg)

        self.resource_id_set(floating_ip.id)
        self._floating_ip = floating_ip

    def handle_delete(self):
        if self.resource_id is not None:
            try:
                self.nova().floating_ips.delete(self.resource_id)
            except clients.novaclient.exceptions.NotFound:
                pass

    def _resolve_attribute(self, key):
        floating_ip = self._get_resource()
        attributes = {
            'pool': getattr(floating_ip, 'pool', None),
            'ip': floating_ip.ip
        }
        return unicode(attributes[key])


class NovaFloatingIpAssociation(resource.Resource):
    PROPERTIES = (
        SERVER, FLOATING_IP
    ) = (
        'server_id', 'floating_ip'
    )

    properties_schema = {
        SERVER: properties.Schema(
            properties.Schema.STRING,
            _('Server to assign floating IP to.'),
            required=True
        ),
        FLOATING_IP: properties.Schema(
            properties.Schema.STRING,
            _('ID of the floating IP to assign to the server.'),
            required=True
        ),
    }

    def FnGetRefId(self):
        return unicode(self.physical_resource_name())

    def handle_create(self):
        server = self.nova().servers.get(self.properties[self.SERVER])
        fl_ip = self.nova().floating_ips.get(self.properties[self.FLOATING_IP])

        self.nova().servers.add_floating_ip(server, fl_ip.ip)
        self.resource_id_set('%s-%s' % (fl_ip.id, fl_ip.ip))

    def handle_delete(self):
        if self.resource_id is None:
            return

        try:
            server = self.nova().servers.get(self.properties[self.SERVER])
            if server:
                fl_ip = self.nova().floating_ips.\
                    get(self.properties[self.FLOATING_IP])
                self.nova().servers.remove_floating_ip(server, fl_ip.ip)
        except clients.novaclient.exceptions.NotFound:
            pass


def resource_mapping():
    return {
        'OS::Nova::FloatingIP': NovaFloatingIp,
        'OS::Nova::FloatingIPAssociation': NovaFloatingIpAssociation,
    }
