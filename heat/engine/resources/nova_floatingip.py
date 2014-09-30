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

from oslo.utils import excutils

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class NovaFloatingIp(resource.Resource):
    PROPERTIES = (POOL,) = ('pool',)

    ATTRIBUTES = (
        POOL_ATTR, IP,
    ) = (
        'pool', 'ip',
    )

    properties_schema = {
        POOL: properties.Schema(
            properties.Schema.STRING,
            description=_('Allocate a floating IP from a given '
                          'floating IP pool.')
        ),
    }

    attributes_schema = {
        POOL_ATTR: attributes.Schema(
            _('Pool from which floating IP is allocated.')
        ),
        IP: attributes.Schema(
            _('Allocated floating IP address.')
        ),
    }

    default_client_name = 'nova'

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
        except Exception as e:
            with excutils.save_and_reraise_exception():
                if self.client_plugin().is_not_found(e):
                    if pool is None:
                        msg = _('Could not allocate floating IP. Probably '
                                'there is no default floating IP pool is '
                                'configured.')
                        LOG.error(msg)

        self.resource_id_set(floating_ip.id)
        self._floating_ip = floating_ip

    def handle_delete(self):
        if self.resource_id is not None:
            try:
                self.nova().floating_ips.delete(self.resource_id)
            except Exception as e:
                self.client_plugin().ignore_not_found(e)

    def _resolve_attribute(self, key):
        floating_ip = self._get_resource()
        attributes = {
            self.POOL_ATTR: getattr(floating_ip, self.POOL_ATTR, None),
            self.IP: floating_ip.ip
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
            required=True,
            update_allowed=True
        ),
        FLOATING_IP: properties.Schema(
            properties.Schema.STRING,
            _('ID of the floating IP to assign to the server.'),
            required=True,
            update_allowed=True
        ),
    }

    def FnGetRefId(self):
        return self.physical_resource_name_or_FnGetRefId()

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
        except Exception as e:
            self.client_plugin().ignore_not_found(e)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            # If floating_ip in prop_diff, we need to remove the old floating
            # ip from the old server, and then to add the new floating ip
            # to the old/new(if the server_id is changed) server.
            # If prop_diff only has the server_id, no need to remove the
            # floating ip from the old server, nova does this automatically
            # when calling add_floating_ip().
            if self.FLOATING_IP in prop_diff:
                self.handle_delete()
            server_id = (prop_diff.get(self.SERVER) or
                         self.properties[self.SERVER])
            fl_ip_id = (prop_diff.get(self.FLOATING_IP) or
                        self.properties[self.FLOATING_IP])
            server = self.nova().servers.get(server_id)
            fl_ip = self.nova().floating_ips.get(fl_ip_id)

            self.nova().servers.add_floating_ip(server, fl_ip.ip)
            self.resource_id_set('%s-%s' % (fl_ip.id, fl_ip.ip))


def resource_mapping():
    return {
        'OS::Nova::FloatingIP': NovaFloatingIp,
        'OS::Nova::FloatingIPAssociation': NovaFloatingIpAssociation,
    }
