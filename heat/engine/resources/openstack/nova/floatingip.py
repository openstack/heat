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
import six

from heat.common import exception
from heat.common.i18n import _
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

    deprecation_msg = _('Please use OS::Neutron::FloatingIP instead.')
    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=deprecation_msg,
        version='11.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=deprecation_msg,
            version='9.0.0',
            previous_status=support.SupportStatus(version='2014.1')
        )
    )

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
                          'floating IP pool. Now that nova-network '
                          'is not supported this represents the '
                          'external network.')
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

    def __init__(self, name, json_snippet, stack):
        super(NovaFloatingIp, self).__init__(name, json_snippet, stack)
        self._floating_ip = None

    def _get_resource(self):
        if self._floating_ip is None and self.resource_id is not None:
            self._floating_ip = self.neutron().show_floatingip(
                self.resource_id)

        return self._floating_ip

    def get_external_network_id(self, pool=None):
        if pool:
            neutron_plugin = self.client_plugin('neutron')
            return neutron_plugin.find_resourceid_by_name_or_id(
                neutron_plugin.RES_TYPE_NETWORK,
                pool)
        ext_filter = {'router:external': True}
        ext_nets = self.neutron().list_networks(**ext_filter)['networks']
        if len(ext_nets) != 1:
            raise exception.Error(
                _('Expected 1 external network, found %d') % len(ext_nets))
        external_network_id = ext_nets[0]['id']
        return external_network_id

    def handle_create(self):
        ext_net_id = self.get_external_network_id(
            pool=self.properties[self.POOL])
        floating_ip = self.neutron().create_floatingip(
            {'floatingip': {'floating_network_id': ext_net_id}})
        self.resource_id_set(floating_ip['floatingip']['id'])
        self._floating_ip = floating_ip

    def handle_delete(self):
        with self.client_plugin('neutron').ignore_not_found:
            self.neutron().delete_floatingip(self.resource_id)

    def _resolve_attribute(self, key):
        if self.resource_id is None:
            return
        floating_ip = self._get_resource()
        attributes = {
            self.POOL_ATTR: floating_ip['floatingip']['floating_network_id'],
            self.IP: floating_ip['floatingip']['floating_ip_address']
        }
        return six.text_type(attributes[key])


class NovaFloatingIpAssociation(resource.Resource):
    """A resource associates Nova floating IP with Nova server resource.

    Resource for associating existing Nova floating IP and Nova server.
    """

    deprecation_msg = _(
        'Please use OS::Neutron::FloatingIPAssociation instead.')
    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=deprecation_msg,
        version='11.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=deprecation_msg,
            version='9.0.0',
            previous_status=support.SupportStatus(version='2014.1')
        )
    )

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
        self.client_plugin().associate_floatingip(
            self.properties[self.SERVER], self.properties[self.FLOATING_IP])
        self.resource_id_set(self.id)

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
            self.client_plugin().dissociate_floatingip(
                self.properties[self.FLOATING_IP])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            # If floating_ip in prop_diff, we need to remove the old floating
            # ip from the old server, and then to add the new floating ip
            # to the old/new(if the server_id is changed) server.
            if self.FLOATING_IP in prop_diff:
                self.handle_delete()
            server_id = (prop_diff.get(self.SERVER) or
                         self.properties[self.SERVER])
            fl_ip_id = (prop_diff.get(self.FLOATING_IP) or
                        self.properties[self.FLOATING_IP])
            self.client_plugin().associate_floatingip(server_id, fl_ip_id)
            self.resource_id_set(self.id)


def resource_mapping():
    return {
        'OS::Nova::FloatingIP': NovaFloatingIp,
        'OS::Nova::FloatingIPAssociation': NovaFloatingIpAssociation,
    }
