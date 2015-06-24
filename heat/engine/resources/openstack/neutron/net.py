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

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class Net(neutron.NeutronResource):
    PROPERTIES = (
        NAME, VALUE_SPECS, ADMIN_STATE_UP, TENANT_ID, SHARED,
        DHCP_AGENT_IDS, PORT_SECURITY_ENABLED,
    ) = (
        'name', 'value_specs', 'admin_state_up', 'tenant_id', 'shared',
        'dhcp_agent_ids', 'port_security_enabled',
    )

    ATTRIBUTES = (
        STATUS, NAME_ATTR, SUBNETS, ADMIN_STATE_UP_ATTR, TENANT_ID_ATTR,
        PORT_SECURITY_ENABLED_ATTR, MTU_ATTR,
    ) = (
        "status", "name", "subnets", "admin_state_up", "tenant_id",
        "port_security_enabled", "mtu",
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying a symbolic name for the network, which is '
              'not required to be unique.'),
            update_allowed=True
        ),
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the "network" object in the '
              'creation request. Parameters are often specific to installed '
              'hardware or extensions.'),
            default={},
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('A boolean value specifying the administrative status of the '
              'network.'),
            default=True,
            update_allowed=True
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the tenant which will own the network. Only '
              'administrative users can set the tenant identifier; this '
              'cannot be changed using authorization policies.')
        ),
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this network should be shared across all tenants. '
              'Note that the default policy setting restricts usage of this '
              'attribute to administrative users only.'),
            default=False,
            update_allowed=True
        ),
        DHCP_AGENT_IDS: properties.Schema(
            properties.Schema.LIST,
            _('The IDs of the DHCP agent to schedule the network. Note that '
              'the default policy setting in Neutron restricts usage of this '
              'property to administrative users only.'),
            update_allowed=True
        ),
        PORT_SECURITY_ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Flag to enable/disable port security on the network. It '
              'provides the default value for the attribute of the ports '
              'created on this network'),
            update_allowed=True,
            support_status=support.SupportStatus(version='5.0.0')
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _("The status of the network."),
            type=attributes.Schema.STRING
        ),
        NAME_ATTR: attributes.Schema(
            _("The name of the network."),
            type=attributes.Schema.STRING
        ),
        SUBNETS: attributes.Schema(
            _("Subnets of this network."),
            type=attributes.Schema.LIST
        ),
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _("The administrative status of the network."),
            type=attributes.Schema.STRING
        ),
        TENANT_ID_ATTR: attributes.Schema(
            _("The tenant owning this network."),
            type=attributes.Schema.STRING
        ),
        PORT_SECURITY_ENABLED_ATTR: attributes.Schema(
            _("Port security enabled of the network."),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.BOOLEAN
        ),
        MTU_ATTR: attributes.Schema(
            _("The maximum transmission unit size(in bytes) for the network."),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.INTEGER
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        dhcp_agent_ids = props.pop(self.DHCP_AGENT_IDS, None)

        net = self.neutron().create_network({'network': props})['network']
        self.resource_id_set(net['id'])

        if dhcp_agent_ids:
            self._replace_dhcp_agents(dhcp_agent_ids)

    def _show_resource(self):
        return self.neutron().show_network(
            self.resource_id)['network']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_network(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)

        dhcp_agent_ids = props.pop(self.DHCP_AGENT_IDS, None)

        if self.DHCP_AGENT_IDS in prop_diff:
            if dhcp_agent_ids is not None:
                self._replace_dhcp_agents(dhcp_agent_ids)
            del prop_diff[self.DHCP_AGENT_IDS]

        if len(prop_diff) > 0:
            self.neutron().update_network(
                self.resource_id, {'network': props})

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def _replace_dhcp_agents(self, dhcp_agent_ids):
        ret = self.neutron().list_dhcp_agent_hosting_networks(
            self.resource_id)
        old = set([agent['id'] for agent in ret['agents']])
        new = set(dhcp_agent_ids)

        for dhcp_agent_id in new - old:
            try:
                self.neutron().add_network_to_dhcp_agent(
                    dhcp_agent_id, {'network_id': self.resource_id})
            except Exception as ex:
                # if 409 is happened, the agent is already associated.
                if not self.client_plugin().is_conflict(ex):
                    raise

        for dhcp_agent_id in old - new:
            try:
                self.neutron().remove_network_from_dhcp_agent(
                    dhcp_agent_id, self.resource_id)
            except Exception as ex:
                # assume 2 patterns about status_code following:
                #  404: the network or agent is already gone
                #  409: the network isn't scheduled by the dhcp_agent
                if not (self.client_plugin().is_conflict(ex) or
                        self.client_plugin().is_not_found(ex)):
                    raise


def resource_mapping():
    return {
        'OS::Neutron::Net': Net,
    }
