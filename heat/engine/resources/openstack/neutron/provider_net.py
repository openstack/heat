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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import net
from heat.engine import support


class ProviderNet(net.Net):
    """A resource for managing Neutron provider networks.

    Provider networks specify details of physical realisation of the existing
    network.

    The default policy usage of this resource is limited to
    administrators only.
    """

    required_service_extension = 'provider'

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        NAME, PROVIDER_NETWORK_TYPE, PROVIDER_PHYSICAL_NETWORK,
        PROVIDER_SEGMENTATION_ID, ADMIN_STATE_UP, SHARED,
        PORT_SECURITY_ENABLED, ROUTER_EXTERNAL,
    ) = (
        'name', 'network_type', 'physical_network',
        'segmentation_id', 'admin_state_up', 'shared',
        'port_security_enabled', 'router_external',

    )

    ATTRIBUTES = (
        STATUS, SUBNETS,
    ) = (
        'status', 'subnets',
    )

    properties_schema = {
        NAME: net.Net.properties_schema[NAME],
        PROVIDER_NETWORK_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying the provider network type for the '
              'network.'),
            update_allowed=True,
            required=True,
            constraints=[
                constraints.AllowedValues(['vlan', 'flat']),
            ]
        ),
        PROVIDER_PHYSICAL_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying physical network mapping for the '
              'network.'),
            update_allowed=True
        ),
        PROVIDER_SEGMENTATION_ID: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying the segmentation id for the '
              'network.'),
            update_allowed=True
        ),
        ADMIN_STATE_UP: net.Net.properties_schema[ADMIN_STATE_UP],
        SHARED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether this network should be shared across all tenants.'),
            default=True,
            update_allowed=True
        ),
        PORT_SECURITY_ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Flag to enable/disable port security on the network. It '
              'provides the default value for the attribute of the ports '
              'created on this network.'),
            update_allowed=True,
            support_status=support.SupportStatus(version='8.0.0')
        ),
        ROUTER_EXTERNAL: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Whether the network contains an external router.'),
            default=False,
            update_allowed=True,
            support_status=support.SupportStatus(version='6.0.0')
        ),
    }

    attributes_schema = {
        STATUS: attributes.Schema(
            _("The status of the network."),
            type=attributes.Schema.STRING
        ),
        SUBNETS: attributes.Schema(
            _("Subnets of this network."),
            type=attributes.Schema.LIST
        ),
    }

    def validate(self):
        """Resource's validation.

        Validates to ensure that segmentation_id is not there for flat
        network type.
        """
        super(ProviderNet, self).validate()

        if (self.properties[self.PROVIDER_SEGMENTATION_ID] and
                self.properties[self.PROVIDER_NETWORK_TYPE] != 'vlan'):
            msg = _('segmentation_id not allowed for flat network type.')
            raise exception.StackValidationFailed(message=msg)

    @staticmethod
    def add_provider_extension(props, key):
        props['provider:' + key] = props.pop(key)

    @staticmethod
    def prepare_provider_properties(props):
        if ProviderNet.PROVIDER_NETWORK_TYPE in props:
            ProviderNet.add_provider_extension(
                props,
                ProviderNet.PROVIDER_NETWORK_TYPE)
        if ProviderNet.PROVIDER_PHYSICAL_NETWORK in props:
            ProviderNet.add_provider_extension(
                props,
                ProviderNet.PROVIDER_PHYSICAL_NETWORK)
        if ProviderNet.PROVIDER_SEGMENTATION_ID in props:
            ProviderNet.add_provider_extension(
                props,
                ProviderNet.PROVIDER_SEGMENTATION_ID)

        if ProviderNet.ROUTER_EXTERNAL in props:
            props['router:external'] = props.pop(ProviderNet.ROUTER_EXTERNAL)

    def handle_create(self):
        """Creates the resource with provided properties.

        Adds 'provider:' extension to the required properties during create.
        """
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        ProviderNet.prepare_provider_properties(props)

        prov_net = self.client().create_network({'network': props})['network']
        self.resource_id_set(prov_net['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Updates the resource with provided properties.

        Adds 'provider:' extension to the required properties during update.
        """
        if prop_diff:
            ProviderNet.prepare_provider_properties(prop_diff)
            self.prepare_update_properties(prop_diff)
            self.client().update_network(self.resource_id,
                                         {'network': prop_diff})


def resource_mapping():
    return {
        'OS::Neutron::ProviderNet': ProviderNet,
    }
