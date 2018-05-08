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
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class Net(neutron.NeutronResource):
    """A resource for managing Neutron net.

    A network is a virtual isolated layer-2 broadcast domain which is typically
    reserved to the tenant who created it, unless the network has been
    explicitly configured to be shared.
    """

    entity = 'network'

    PROPERTIES = (
        NAME, VALUE_SPECS, ADMIN_STATE_UP, TENANT_ID, SHARED,
        DHCP_AGENT_IDS, PORT_SECURITY_ENABLED, QOS_POLICY,
        DNS_DOMAIN, TAGS,
    ) = (
        'name', 'value_specs', 'admin_state_up', 'tenant_id', 'shared',
        'dhcp_agent_ids', 'port_security_enabled', 'qos_policy',
        'dns_domain', 'tags',
    )

    ATTRIBUTES = (
        STATUS, NAME_ATTR, SUBNETS, ADMIN_STATE_UP_ATTR, TENANT_ID_ATTR,
        PORT_SECURITY_ENABLED_ATTR, MTU_ATTR, QOS_POLICY_ATTR, L2_ADJACENCY,
        SEGMENTS,
    ) = (
        "status", "name", "subnets", "admin_state_up", "tenant_id",
        "port_security_enabled", "mtu", 'qos_policy_id', 'l2_adjacency',
        'segments',
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
            _('Extra parameters to include in the request. Parameters are '
              'often specific to installed hardware or extensions.'),
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
              'created on this network.'),
            update_allowed=True,
            support_status=support.SupportStatus(version='5.0.0')
        ),
        QOS_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('The name or ID of QoS policy to attach to this network.'),
            constraints=[
                constraints.CustomConstraint('neutron.qos_policy')
            ],
            update_allowed=True,
            support_status=support.SupportStatus(version='6.0.0')
        ),
        DNS_DOMAIN: properties.Schema(
            properties.Schema.STRING,
            _('DNS domain associated with this network.'),
            constraints=[
                constraints.CustomConstraint('dns_domain')
            ],
            update_allowed=True,
            support_status=support.SupportStatus(version='7.0.0')
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('The tags to be added to the network.'),
            schema=properties.Schema(properties.Schema.STRING),
            update_allowed=True,
            support_status=support.SupportStatus(version='9.0.0')
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
        QOS_POLICY_ATTR: attributes.Schema(
            _("The QoS policy ID attached to this network."),
            type=attributes.Schema.STRING,
            support_status=support.SupportStatus(version='6.0.0'),
        ),
        L2_ADJACENCY: attributes.Schema(
            _("A boolean value for L2 adjacency, True means that you can "
              "expect L2 connectivity throughout the Network."),
            type=attributes.Schema.BOOLEAN,
            support_status=support.SupportStatus(version='9.0.0'),
        ),
        SEGMENTS: attributes.Schema(
            _("The segments of this network."),
            type=attributes.Schema.LIST,
            support_status=support.SupportStatus(version='11.0.0'),
        ),
    }

    def translation_rules(self, properties):
        return [translation.TranslationRule(
            properties,
            translation.TranslationRule.RESOLVE,
            [self.QOS_POLICY],
            client_plugin=self.client_plugin(),
            finder='get_qos_policy_id')]

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        dhcp_agent_ids = props.pop(self.DHCP_AGENT_IDS, None)
        qos_policy = props.pop(self.QOS_POLICY, None)
        tags = props.pop(self.TAGS, [])
        if qos_policy:
            props['qos_policy_id'] = qos_policy

        net = self.client().create_network({'network': props})['network']
        self.resource_id_set(net['id'])

        if dhcp_agent_ids:
            self._replace_dhcp_agents(dhcp_agent_ids)

        if tags:
            self.set_tags(tags)

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        self._store_config_default_properties(attributes)
        return self.is_built(attributes)

    def handle_delete(self):
        try:
            self.client().delete_network(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            if self.DHCP_AGENT_IDS in prop_diff:
                dhcp_agent_ids = prop_diff.pop(self.DHCP_AGENT_IDS) or []
                self._replace_dhcp_agents(dhcp_agent_ids)
            if self.QOS_POLICY in prop_diff:
                qos_policy = prop_diff.pop(self.QOS_POLICY)
                prop_diff[
                    'qos_policy_id'] = self.client_plugin().get_qos_policy_id(
                    qos_policy) if qos_policy else None
            if self.TAGS in prop_diff:
                self.set_tags(prop_diff.pop(self.TAGS))
        if prop_diff:
            self.client().update_network(self.resource_id,
                                         {'network': prop_diff})

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def _replace_dhcp_agents(self, dhcp_agent_ids):
        ret = self.client().list_dhcp_agent_hosting_networks(
            self.resource_id)
        old = set([agent['id'] for agent in ret['agents']])
        new = set(dhcp_agent_ids)

        for dhcp_agent_id in new - old:
            try:
                self.client().add_network_to_dhcp_agent(
                    dhcp_agent_id, {'network_id': self.resource_id})
            except Exception as ex:
                # if 409 is happened, the agent is already associated.
                if not self.client_plugin().is_conflict(ex):
                    raise

        for dhcp_agent_id in old - new:
            try:
                self.client().remove_network_from_dhcp_agent(
                    dhcp_agent_id, self.resource_id)
            except Exception as ex:
                # assume 2 patterns about status_code following:
                #  404: the network or agent is already gone
                #  409: the network isn't scheduled by the dhcp_agent
                if not (self.client_plugin().is_conflict(ex) or
                        self.client_plugin().is_not_found(ex)):
                    raise

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(Net, self).parse_live_resource_data(
            resource_properties, resource_data)
        result.pop(self.SHARED)
        result[self.QOS_POLICY] = resource_data.get('qos_policy_id')
        try:
            dhcp = self.client().list_dhcp_agent_hosting_networks(
                self.resource_id)
            dhcp_agents = set([agent['id'] for agent in dhcp['agents']])
            result.update({self.DHCP_AGENT_IDS: list(dhcp_agents)})
        except self.client_plugin().exceptions.Forbidden:
            # Just don't add dhcp_clients if we can't get values.
            pass
        return result

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        if name == self.SEGMENTS:
            return [segment.to_dict() for segment in list(self.client(
                'openstack').network.segments(network_id=self.resource_id))]
        attributes = self._show_resource()
        return attributes[name]


def resource_mapping():
    return {
        'OS::Neutron::Net': Net,
    }
