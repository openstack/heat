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
from oslo_serialization import jsonutils
import six

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.neutron import neutron
from heat.engine.resources.openstack.neutron import subnet
from heat.engine import support
from heat.engine import translation

LOG = logging.getLogger(__name__)


class Port(neutron.NeutronResource):
    """A resource for managing Neutron ports.

    A port represents a virtual switch port on a logical network switch.
    Virtual instances attach their interfaces into ports. The logical port also
    defines the MAC address and the IP address(es) to be assigned to the
    interfaces plugged into them. When IP addresses are associated to a port,
    this also implies the port is associated with a subnet, as the IP address
    was taken from the allocation pool for a specific subnet.
    """

    entity = 'port'

    PROPERTIES = (
        NAME, NETWORK_ID, NETWORK, FIXED_IPS, SECURITY_GROUPS,
        REPLACEMENT_POLICY, DEVICE_ID, DEVICE_OWNER, DNS_NAME,
        TAGS,
    ) = (
        'name', 'network_id', 'network', 'fixed_ips', 'security_groups',
        'replacement_policy', 'device_id', 'device_owner', 'dns_name',
        'tags',
    )

    EXTRA_PROPERTIES = (
        VALUE_SPECS, ADMIN_STATE_UP, MAC_ADDRESS,
        ALLOWED_ADDRESS_PAIRS, VNIC_TYPE, QOS_POLICY,
        PORT_SECURITY_ENABLED,
    ) = (
        'value_specs', 'admin_state_up', 'mac_address',
        'allowed_address_pairs', 'binding:vnic_type', 'qos_policy',
        'port_security_enabled',
    )

    _FIXED_IP_KEYS = (
        FIXED_IP_SUBNET_ID, FIXED_IP_SUBNET, FIXED_IP_IP_ADDRESS,
    ) = (
        'subnet_id', 'subnet', 'ip_address',
    )

    _ALLOWED_ADDRESS_PAIR_KEYS = (
        ALLOWED_ADDRESS_PAIR_MAC_ADDRESS, ALLOWED_ADDRESS_PAIR_IP_ADDRESS,
    ) = (
        'mac_address', 'ip_address',
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, DEVICE_ID_ATTR, DEVICE_OWNER_ATTR, FIXED_IPS_ATTR,
        MAC_ADDRESS_ATTR, NAME_ATTR, NETWORK_ID_ATTR, SECURITY_GROUPS_ATTR,
        STATUS, TENANT_ID, ALLOWED_ADDRESS_PAIRS_ATTR, SUBNETS_ATTR,
        PORT_SECURITY_ENABLED_ATTR, QOS_POLICY_ATTR, DNS_ASSIGNMENT,
        NETWORK_ATTR,
    ) = (
        'admin_state_up', 'device_id', 'device_owner', 'fixed_ips',
        'mac_address', 'name', 'network_id', 'security_groups',
        'status', 'tenant_id', 'allowed_address_pairs', 'subnets',
        'port_security_enabled', 'qos_policy_id', 'dns_assignment', 'network',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A symbolic name for this port.'),
            update_allowed=True
        ),
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='5.0.0',
                message=_('Use property %s.') % NETWORK,
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.2'
                )
            ),
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
        ),

        NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Network this port belongs to. If you plan to use current port '
              'to assign Floating IP, you should specify %(fixed_ips)s '
              'with %(subnet)s. Note if this changes to a different network '
              'update, the port will be replaced.') %
            {'fixed_ips': FIXED_IPS, 'subnet': FIXED_IP_SUBNET},
            support_status=support.SupportStatus(version='2014.2'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
        ),
        DEVICE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Device ID of this port.'),
            update_allowed=True,
            default=''
        ),
        DEVICE_OWNER: properties.Schema(
            properties.Schema.STRING,
            _('Name of the network owning the port. '
              'The value is typically network:floatingip '
              'or network:router_interface or network:dhcp.'),
            update_allowed=True,
            default=''
        ),
        FIXED_IPS: properties.Schema(
            properties.Schema.LIST,
            _('Desired IPs for this port.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    FIXED_IP_SUBNET_ID: properties.Schema(
                        properties.Schema.STRING,
                        support_status=support.SupportStatus(
                            status=support.HIDDEN,
                            version='5.0.0',
                            message=_('Use property %s.') % FIXED_IP_SUBNET,
                            previous_status=support.SupportStatus(
                                status=support.DEPRECATED,
                                version='2014.2 '
                            )
                        ),
                        constraints=[
                            constraints.CustomConstraint('neutron.subnet')
                        ]
                    ),
                    FIXED_IP_SUBNET: properties.Schema(
                        properties.Schema.STRING,
                        _('Subnet in which to allocate the IP address for '
                          'this port.'),
                        support_status=support.SupportStatus(version='2014.2'),
                        constraints=[
                            constraints.CustomConstraint('neutron.subnet')
                        ]
                    ),
                    FIXED_IP_IP_ADDRESS: properties.Schema(
                        properties.Schema.STRING,
                        _('IP address desired in the subnet for this port.'),
                        constraints=[
                            constraints.CustomConstraint('ip_addr')
                        ]
                    ),
                },
            ),
            update_allowed=True
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Security group IDs to associate with this port.'),
            update_allowed=True
        ),
        REPLACEMENT_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('Policy on how to respond to a stack-update for this resource. '
              'REPLACE_ALWAYS will replace the port regardless of any '
              'property changes. AUTO will update the existing port for any '
              'changed update-allowed property.'),
            default='AUTO',
            constraints=[
                constraints.AllowedValues(['REPLACE_ALWAYS', 'AUTO']),
            ],
            update_allowed=True,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='9.0.0',
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='6.0.0',
                    message=_('Replacement policy used to work around flawed '
                              'nova/neutron port interaction which has been '
                              'fixed since Liberty.'),
                    previous_status=support.SupportStatus(version='2014.2')
                )
            )
        ),
        DNS_NAME: properties.Schema(
            properties.Schema.STRING,
            _('DNS name associated with the port.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('dns_name')
            ],
            support_status=support.SupportStatus(version='7.0.0'),
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('The tags to be added to the port.'),
            schema=properties.Schema(properties.Schema.STRING),
            update_allowed=True,
            support_status=support.SupportStatus(version='9.0.0')
        ),
    }

    # NOTE(prazumovsky): properties_schema has been separated because some
    # properties used in server for creating internal port.
    extra_properties_schema = {
        VALUE_SPECS: properties.Schema(
            properties.Schema.MAP,
            _('Extra parameters to include in the request.'),
            default={},
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of this port.'),
            default=True,
            update_allowed=True
        ),
        MAC_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('MAC address to give to this port. The default update policy '
              'of this property in neutron is that allow admin role only.'),
            constraints=[
                constraints.CustomConstraint('mac_addr')
            ],
            update_allowed=True,
        ),
        ALLOWED_ADDRESS_PAIRS: properties.Schema(
            properties.Schema.LIST,
            _('Additional MAC/IP address pairs allowed to pass through the '
              'port.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ALLOWED_ADDRESS_PAIR_MAC_ADDRESS: properties.Schema(
                        properties.Schema.STRING,
                        _('MAC address to allow through this port.'),
                        constraints=[
                            constraints.CustomConstraint('mac_addr')
                        ]
                    ),
                    ALLOWED_ADDRESS_PAIR_IP_ADDRESS: properties.Schema(
                        properties.Schema.STRING,
                        _('IP address to allow through this port.'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('net_cidr')
                        ]
                    ),
                },
            ),
            update_allowed=True,
        ),
        VNIC_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The vnic type to be bound on the neutron port. '
              'To support SR-IOV PCI passthrough networking, you can request '
              'that the neutron port to be realized as normal (virtual nic), '
              'direct (pci passthrough), or macvtap '
              '(virtual interface with a tap-like software interface). Note '
              'that this only works for Neutron deployments that support '
              'the bindings extension.'),
            constraints=[
                constraints.AllowedValues(['normal', 'direct', 'macvtap',
                                           'direct-physical', 'baremetal']),
            ],
            support_status=support.SupportStatus(version='2015.1'),
            update_allowed=True,
            default='normal'
        ),
        PORT_SECURITY_ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Flag to enable/disable port security on the port. '
              'When disable this feature(set it to False), there will be no '
              'packages filtering, like security-group and address-pairs.'),
            update_allowed=True,
            support_status=support.SupportStatus(version='5.0.0')
        ),
        QOS_POLICY: properties.Schema(
            properties.Schema.STRING,
            _('The name or ID of QoS policy to attach to this port.'),
            constraints=[
                constraints.CustomConstraint('neutron.qos_policy')
            ],
            update_allowed=True,
            support_status=support.SupportStatus(version='6.0.0')
        ),
    }

    # Need to update properties_schema with other properties before
    # initialisation, because resource should contain all properties before
    # creating. Also, documentation should correctly resolves resource
    # properties schema.
    properties_schema.update(extra_properties_schema)

    attributes_schema = {
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _("The administrative state of this port."),
            type=attributes.Schema.STRING
        ),
        DEVICE_ID_ATTR: attributes.Schema(
            _("Unique identifier for the device."),
            type=attributes.Schema.STRING
        ),
        DEVICE_OWNER: attributes.Schema(
            _("Name of the network owning the port."),
            type=attributes.Schema.STRING
        ),
        FIXED_IPS_ATTR: attributes.Schema(
            _("Fixed IP addresses."),
            type=attributes.Schema.LIST
        ),
        MAC_ADDRESS_ATTR: attributes.Schema(
            _("MAC address of the port."),
            type=attributes.Schema.STRING
        ),
        NAME_ATTR: attributes.Schema(
            _("Friendly name of the port."),
            type=attributes.Schema.STRING
        ),
        NETWORK_ID_ATTR: attributes.Schema(
            _("Unique identifier for the network owning the port."),
            type=attributes.Schema.STRING
        ),
        SECURITY_GROUPS_ATTR: attributes.Schema(
            _("A list of security groups for the port."),
            type=attributes.Schema.LIST
        ),
        STATUS: attributes.Schema(
            _("The status of the port."),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _("Tenant owning the port."),
            type=attributes.Schema.STRING
        ),
        ALLOWED_ADDRESS_PAIRS_ATTR: attributes.Schema(
            _("Additional MAC/IP address pairs allowed to pass through "
              "a port."),
            type=attributes.Schema.LIST
        ),
        SUBNETS_ATTR: attributes.Schema(
            _("A list of all subnet attributes for the port."),
            type=attributes.Schema.LIST
        ),
        PORT_SECURITY_ENABLED_ATTR: attributes.Schema(
            _("Port security enabled of the port."),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.BOOLEAN
        ),
        QOS_POLICY_ATTR: attributes.Schema(
            _("The QoS policy ID attached to this port."),
            type=attributes.Schema.STRING,
            support_status=support.SupportStatus(version='6.0.0'),
        ),
        DNS_ASSIGNMENT: attributes.Schema(
            _("The DNS assigned to this port."),
            type=attributes.Schema.MAP,
            support_status=support.SupportStatus(version='7.0.0'),
        ),
        NETWORK_ATTR: attributes.Schema(
            _("The attributes of the network owning the port. (The full list "
              "of response parameters can be found in the `Openstack "
              "Networking service API reference "
              "<https://developer.openstack.org/api-ref/network/>`_.) The "
              "following examples demonstrate some (not all) possible "
              "expressions. (Obtains the network, the MTU (Maximum "
              "transmission unit), the network tags and the l2_adjacency "
              "property): "
              "``{get_attr: [<port>, network]}``, "
              "``{get_attr: [<port>, network, mtu]}``, "
              "``{get_attr: [<port>, network, tags]}?``, "
              "``{get_attr: [<port>, network, l2_adjacency]}``."),
            type=attributes.Schema.MAP,
            support_status=support.SupportStatus(version='11.0.0'),
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.NETWORK],
                value_path=[self.NETWORK_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.FIXED_IPS, self.FIXED_IP_SUBNET],
                value_name=self.FIXED_IP_SUBNET_ID
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.NETWORK],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_NETWORK
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.FIXED_IPS, self.FIXED_IP_SUBNET],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET
            )
        ]

    def add_dependencies(self, deps):
        super(Port, self).add_dependencies(deps)
        # Depend on any Subnet in this template with the same
        # network_id as this network_id.
        # It is not known which subnet a port might be assigned
        # to so all subnets in a network should be created before
        # the ports in that network.
        for res in six.itervalues(self.stack):
            if res.has_interface('OS::Neutron::Subnet'):
                try:
                    dep_network = res.properties.get(subnet.Subnet.NETWORK)
                    network = self.properties[self.NETWORK]
                except (ValueError, TypeError):
                    # Properties errors will be caught later in validation,
                    # where we can report them in their proper context.
                    continue
                if dep_network == network:
                    deps += (self, res)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        props['network_id'] = props.pop(self.NETWORK)
        self._prepare_port_properties(props)
        qos_policy = props.pop(self.QOS_POLICY, None)
        tags = props.pop(self.TAGS, [])
        if qos_policy:
            props['qos_policy_id'] = self.client_plugin().get_qos_policy_id(
                qos_policy)

        port = self.client().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

        if tags:
            self.set_tags(tags)

    def _prepare_port_properties(self, props, prepare_for_update=False):
        if self.FIXED_IPS in props:
            fixed_ips = props[self.FIXED_IPS]
            if fixed_ips:
                for fixed_ip in fixed_ips:
                    for key, value in list(fixed_ip.items()):
                        if value is None:
                            fixed_ip.pop(key)
                    if self.FIXED_IP_SUBNET in fixed_ip:
                        fixed_ip[
                            'subnet_id'] = fixed_ip.pop(self.FIXED_IP_SUBNET)
            else:
                # Passing empty list would have created a port without
                # fixed_ips during CREATE and released the existing
                # fixed_ips during UPDATE (default neutron behaviour).
                # However, for backward compatibility we will let neutron
                # assign ip for CREATE and leave the assigned ips during
                # UPDATE by not passing it. ref bug #1538473.
                del props[self.FIXED_IPS]
        # delete empty MAC addresses so that Neutron validation code
        # wouldn't fail as it not accepts Nones
        if self.ALLOWED_ADDRESS_PAIRS in props:
            address_pairs = props[self.ALLOWED_ADDRESS_PAIRS]
            if address_pairs:
                for pair in address_pairs:
                    if (self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS in pair
                        and pair[
                            self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS] is None):
                        del pair[self.ALLOWED_ADDRESS_PAIR_MAC_ADDRESS]
            else:
                props[self.ALLOWED_ADDRESS_PAIRS] = []
        # if without 'security_groups', don't set the 'security_groups'
        # property when creating, neutron will create the port with the
        # 'default' securityGroup. If has the 'security_groups' and the
        # value is [], which means to create the port without securityGroup.
        if self.SECURITY_GROUPS in props:
            if props.get(self.SECURITY_GROUPS) is not None:
                props[self.SECURITY_GROUPS] = self.client_plugin(
                ).get_secgroup_uuids(props.get(self.SECURITY_GROUPS))
            else:
                # And the update should has the same behavior.
                if prepare_for_update:
                    props[self.SECURITY_GROUPS] = self.client_plugin(
                    ).get_secgroup_uuids(['default'])

        if self.REPLACEMENT_POLICY in props:
            del(props[self.REPLACEMENT_POLICY])

    def _store_config_default_properties(self, attrs):
        """A method for storing properties default values.

        A method allows to store properties default values, which cannot be
        defined in schema in case of specifying in config file.
        """
        super(Port, self)._store_config_default_properties(attrs)
        if self.VNIC_TYPE in attrs:
            self.data_set(self.VNIC_TYPE, attrs[self.VNIC_TYPE])

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        self._store_config_default_properties(attributes)
        return self.is_built(attributes)

    def handle_delete(self):
        try:
            self.client().delete_port(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(Port, self).parse_live_resource_data(
            resource_properties, resource_data)
        result[self.QOS_POLICY] = resource_data.get('qos_policy_id')
        result.pop(self.MAC_ADDRESS)
        fixed_ips = resource_data.get(self.FIXED_IPS) or []
        if fixed_ips:
            result.update({self.FIXED_IPS: []})
            for fixed_ip in fixed_ips:
                result[self.FIXED_IPS].append(
                    {self.FIXED_IP_SUBNET: fixed_ip.get('subnet_id'),
                     self.FIXED_IP_IP_ADDRESS: fixed_ip.get('ip_address')})
        return result

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        if name == self.SUBNETS_ATTR:
            subnets = []
            try:
                fixed_ips = self._show_resource().get('fixed_ips', [])
                for fixed_ip in fixed_ips:
                    subnet_id = fixed_ip.get('subnet_id')
                    if subnet_id:
                        subnets.append(self.client().show_subnet(
                            subnet_id)['subnet'])
            except Exception as ex:
                LOG.warning("Failed to fetch resource attributes: %s", ex)
                return
            return subnets
        if name == self.NETWORK_ATTR:
            try:
                return self.client().show_network(
                    self._show_resource().get('network_id'))['network']
            except Exception as ex:
                LOG.warning("Failed to fetch resource attributes: %s", ex)
                return
        return super(Port, self)._resolve_attribute(name)

    def needs_replace(self, after_props):
        """Mandatory replace based on props."""
        return after_props.get(self.REPLACEMENT_POLICY) == 'REPLACE_ALWAYS'

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            if self.QOS_POLICY in prop_diff:
                qos_policy = prop_diff.pop(self.QOS_POLICY)
                prop_diff['qos_policy_id'] = self.client_plugin(
                    ).get_qos_policy_id(qos_policy) if qos_policy else None

            if self.TAGS in prop_diff:
                tags = prop_diff.pop(self.TAGS)
                self.set_tags(tags)

            self._prepare_port_properties(prop_diff, prepare_for_update=True)
            if prop_diff:
                LOG.debug('updating port with %s', prop_diff)
                self.client().update_port(self.resource_id,
                                          {'port': prop_diff})

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def prepare_for_replace(self):
        # if the port has not been created yet, return directly
        if self.resource_id is None:
            return
        # store port fixed_ips for restoring after failed update
        # Ignore if the port does not exist in neutron (deleted)
        with self.client_plugin().ignore_not_found:
            fixed_ips = self._show_resource().get('fixed_ips', [])
            self.data_set('port_fip', jsonutils.dumps(fixed_ips))
            # reset fixed_ips for this port by setting fixed_ips to []
            props = {'fixed_ips': []}
            self.client().update_port(self.resource_id, {'port': props})

    def restore_prev_rsrc(self, convergence=False):
        # In case of convergence, during rollback, the previous rsrc is
        # already selected and is being acted upon.
        if convergence:
            prev_port = self
            existing_port, rsrc_owning_stack, stack = resource.Resource.load(
                prev_port.context, prev_port.replaced_by,
                prev_port.stack.current_traversal, True,
                prev_port.stack.defn._resource_data
            )
            existing_port_id = existing_port.resource_id
        else:
            backup_stack = self.stack._backup_stack()
            prev_port = backup_stack.resources.get(self.name)
            existing_port_id = self.resource_id

        if existing_port_id:
            # reset fixed_ips to [] for new resource
            props = {'fixed_ips': []}
            self.client().update_port(existing_port_id, {'port': props})

        fixed_ips = prev_port.data().get('port_fip', [])
        if fixed_ips and prev_port.resource_id:
            # restore ip for old port
            prev_port_props = {'fixed_ips': jsonutils.loads(fixed_ips)}
            self.client().update_port(prev_port.resource_id,
                                      {'port': prev_port_props})


def resource_mapping():
    return {
        'OS::Neutron::Port': Port,
    }
