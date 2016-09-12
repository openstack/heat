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
from oslo_utils import excutils
import six

from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

LOG = logging.getLogger(__name__)


class NovaFloatingIp(resource.Resource):
    """A resource for managing Nova floating IPs.

    Floating IP addresses can change their association between instances by
    action of the user. One of the most common use cases for floating IPs is
    to provide public IP addresses to a private cloud, where there are a
    limited number of IP addresses available. Another is for a public cloud
    user to have a "static" IP address that can be reassigned when an instance
    is upgraded or moved.
    """
    support_status = support.SupportStatus(version='2014.1')

    required_service_extension = 'os-floating-ips'

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
            _('Pool from which floating IP is allocated.'),
            type=attributes.Schema.STRING
        ),
        IP: attributes.Schema(
            _('Allocated floating IP address.'),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'nova'

    entity = 'floating_ips'

    def __init__(self, name, json_snippet, stack):
        super(NovaFloatingIp, self).__init__(name, json_snippet, stack)
        self._floating_ip = None

    def _get_resource(self):
        if self._floating_ip is None and self.resource_id is not None:
            self._floating_ip = self.client().floating_ips.get(
                self.resource_id)

        return self._floating_ip

    def handle_create(self):
        try:
            pool = self.properties[self.POOL]
            floating_ip = self.client().floating_ips.create(pool=pool)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                if self.client_plugin().is_not_found(e):
                    if pool is None:
                        LOG.error(_LE('Could not allocate floating IP. '
                                      'Probably there is no default floating'
                                      ' IP pool is configured.'))

        self.resource_id_set(floating_ip.id)
        self._floating_ip = floating_ip

    def _resolve_attribute(self, key):
        if self.resource_id is None:
            return
        floating_ip = self._get_resource()
        attributes = {
            self.POOL_ATTR: getattr(floating_ip, self.POOL_ATTR, None),
            self.IP: floating_ip.ip
        }
        return six.text_type(attributes[key])


class NovaFloatingIpAssociation(resource.Resource):
    """A resource associates Nova floating IP with Nova server resource.

    Resource for associating existing Nova floating IP and Nova server.
    """

    support_status = support.SupportStatus(version='2014.1')

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
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('nova.server')
            ]
        ),
        FLOATING_IP: properties.Schema(
            properties.Schema.STRING,
            _('ID of the floating IP to assign to the server.'),
            required=True,
            update_allowed=True
        ),
    }

    default_client_name = 'nova'

    def get_reference_id(self):
        return self.physical_resource_name_or_FnGetRefId()

    def handle_create(self):
        server = self.client().servers.get(self.properties[self.SERVER])
        fl_ip = self.client().floating_ips.get(
            self.properties[self.FLOATING_IP])

        self.client().servers.add_floating_ip(server, fl_ip.ip)
        self.resource_id_set(self.id)

    def handle_delete(self):
        if self.resource_id is None:
            return

        try:
            server = self.client().servers.get(self.properties[self.SERVER])
            if server:
                fl_ip = self.client().floating_ips.get(
                    self.properties[self.FLOATING_IP])
                self.client().servers.remove_floating_ip(server, fl_ip.ip)
        except Exception as e:
            self.client_plugin().ignore_conflict_and_not_found(e)

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
            server = self.client().servers.get(server_id)
            fl_ip = self.client().floating_ips.get(fl_ip_id)

            self.client().servers.add_floating_ip(server, fl_ip.ip)
            self.resource_id_set(self.id)


def resource_mapping():
    return {
        'OS::Nova::FloatingIP': NovaFloatingIp,
        'OS::Nova::FloatingIPAssociation': NovaFloatingIpAssociation,
    }
