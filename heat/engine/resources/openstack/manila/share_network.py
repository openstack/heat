#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class ManilaShareNetwork(resource.Resource):
    """A resource that stores network information for share servers.

    Stores network information that will be used by share servers,
    where shares are hosted.
    """

    support_status = support.SupportStatus(version='5.0.0')

    PROPERTIES = (
        NAME, NEUTRON_NETWORK, NEUTRON_SUBNET, NOVA_NETWORK,
        DESCRIPTION, SECURITY_SERVICES,
    ) = (
        'name', 'neutron_network', 'neutron_subnet', 'nova_network',
        'description', 'security_services',
    )

    ATTRIBUTES = (
        SEGMENTATION_ID, CIDR, IP_VERSION, NETWORK_TYPE,
    ) = (
        'segmentation_id', 'cidr', 'ip_version', 'network_type',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the share network.'),
            update_allowed=True
        ),
        NEUTRON_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Neutron network id.'),
            update_allowed=True,
            constraints=[constraints.CustomConstraint('neutron.network')]
        ),
        NEUTRON_SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('Neutron subnet id.'),
            update_allowed=True,
            constraints=[constraints.CustomConstraint('neutron.subnet')]
        ),
        NOVA_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Nova network id.'),
            update_allowed=True,
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Share network description.'),
            update_allowed=True
        ),
        SECURITY_SERVICES: properties.Schema(
            properties.Schema.LIST,
            _('A list of security services IDs or names.'),
            schema=properties.Schema(
                properties.Schema.STRING
            ),
            update_allowed=True,
            default=[]
        )
    }

    attributes_schema = {
        SEGMENTATION_ID: attributes.Schema(
            _('VLAN ID for VLAN networks or tunnel-id for GRE/VXLAN '
              'networks.'),
            type=attributes.Schema.STRING
        ),
        CIDR: attributes.Schema(
            _('CIDR of subnet.'),
            type=attributes.Schema.STRING
        ),
        IP_VERSION: attributes.Schema(
            _('Version of IP address.'),
            type=attributes.Schema.STRING
        ),
        NETWORK_TYPE: attributes.Schema(
            _('The physical mechanism by which the virtual network is '
              'implemented.'),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'manila'

    entity = 'share_networks'

    def _request_network(self):
        return self.client().share_networks.get(self.resource_id)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        network = self._request_network()
        return getattr(network, name, None)

    def validate(self):
        super(ManilaShareNetwork, self).validate()
        if (self.properties[self.NEUTRON_NETWORK] and
                self.properties[self.NOVA_NETWORK]):
            raise exception.ResourcePropertyConflict(self.NEUTRON_NETWORK,
                                                     self.NOVA_NETWORK)

        if (self.properties[self.NOVA_NETWORK] and
                self.properties[self.NEUTRON_SUBNET]):
            raise exception.ResourcePropertyConflict(self.NEUTRON_SUBNET,
                                                     self.NOVA_NETWORK)

        if self.is_using_neutron() and self.properties[self.NOVA_NETWORK]:
            msg = _('With Neutron enabled you need to pass Neutron network '
                    'and Neutron subnet instead of Nova network')
            raise exception.StackValidationFailed(message=msg)

        if (self.properties[self.NEUTRON_NETWORK] and not
                self.properties[self.NEUTRON_SUBNET]):
            raise exception.ResourcePropertyDependency(
                prop1=self.NEUTRON_NETWORK, prop2=self.NEUTRON_SUBNET)

        if (self.properties[self.NEUTRON_NETWORK] and
                self.properties[self.NEUTRON_SUBNET]):
            plg = self.client_plugin('neutron')
            subnet_id = plg.find_resourceid_by_name_or_id(
                plg.RES_TYPE_SUBNET, self.properties[self.NEUTRON_SUBNET])
            net_id = plg.network_id_from_subnet_id(subnet_id)
            provided_net_id = plg.find_resourceid_by_name_or_id(
                plg.RES_TYPE_NETWORK, self.properties[self.NEUTRON_NETWORK])
            if net_id != provided_net_id:
                msg = (_('Provided %(subnet)s does not belong '
                         'to provided %(network)s.')
                       % {'subnet': self.NEUTRON_SUBNET,
                          'network': self.NEUTRON_NETWORK})
                raise exception.StackValidationFailed(message=msg)

    def translation_rules(self, props):
        neutron_client_plugin = self.client_plugin('neutron')
        translation_rules = [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.NEUTRON_NETWORK],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_NETWORK
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.NEUTRON_SUBNET],
                client_plugin=neutron_client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=neutron_client_plugin.RES_TYPE_SUBNET
            )
        ]
        return translation_rules

    def handle_create(self):
        neutron_subnet_id = self.properties[self.NEUTRON_SUBNET]
        neutron_net_id = self.properties[self.NEUTRON_NETWORK]
        if neutron_subnet_id and not neutron_net_id:
            neutron_net_id = self.client_plugin(
                'neutron').network_id_from_subnet_id(neutron_subnet_id)
        network = self.client().share_networks.create(
            name=self.properties[self.NAME],
            neutron_net_id=neutron_net_id,
            neutron_subnet_id=neutron_subnet_id,
            nova_net_id=self.properties[self.NOVA_NETWORK],
            description=self.properties[self.DESCRIPTION])
        self.resource_id_set(network.id)

        for service in self.properties.get(self.SECURITY_SERVICES):
            self.client().share_networks.add_security_service(
                self.resource_id,
                self.client_plugin().get_security_service(service).id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if self.SECURITY_SERVICES in prop_diff:
            services = prop_diff.pop(self.SECURITY_SERVICES)
            s_curr = set([self.client_plugin().get_security_service(s).id
                          for s in self.properties.get(
                         self.SECURITY_SERVICES)])
            s_new = set([self.client_plugin().get_security_service(s).id
                        for s in services])
            for service in s_curr - s_new:
                self.client().share_networks.remove_security_service(
                    self.resource_id, service)
            for service in s_new - s_curr:
                self.client().share_networks.add_security_service(
                    self.resource_id, service)

        if prop_diff:
            neutron_subnet_id = prop_diff.get(self.NEUTRON_SUBNET)
            neutron_net_id = prop_diff.get(self.NEUTRON_NETWORK)
            if neutron_subnet_id and not neutron_net_id:
                neutron_net_id = self.client_plugin(
                    'neutron').network_id_from_subnet_id(neutron_subnet_id)

            self.client().share_networks.update(
                self.resource_id,
                name=prop_diff.get(self.NAME),
                neutron_net_id=neutron_net_id,
                neutron_subnet_id=neutron_subnet_id,
                nova_net_id=prop_diff.get(self.NOVA_NETWORK),
                description=prop_diff.get(self.DESCRIPTION))

    def parse_live_resource_data(self, resource_properties, resource_data):
        result = super(ManilaShareNetwork, self).parse_live_resource_data(
            resource_properties, resource_data)
        sec_list = self.client().security_services.list(
            search_opts={'share_network_id': self.resource_id})
        result.update({
            self.NOVA_NETWORK: resource_data.get('nova_net_id'),
            self.NEUTRON_NETWORK: resource_data.get('neutron_net_id'),
            self.NEUTRON_SUBNET: resource_data.get('neutron_subnet_id'),
            self.SECURITY_SERVICES: [service.id for service in sec_list]}
        )
        return result


def resource_mapping():
    return {'OS::Manila::ShareNetwork': ManilaShareNetwork}
