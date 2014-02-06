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
from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.neutron import net


class ProviderNet(net.Net):
    PROPERTIES = (
        NAME, PROVIDER_NETWORK_TYPE, PROVIDER_PHYSICAL_NETWORK,
        PROVIDER_SEGMENTATION_ID, ADMIN_STATE_UP, SHARED,
    ) = (
        'name', 'network_type', 'physical_network',
        'segmentation_id', 'admin_state_up', 'shared',
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
            update_allowed=True,
            required=True,
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
    }

    update_allowed_keys = ('Properties',)

    attributes_schema = {
        "status": _("The status of the network."),
        "subnets": _("Subnets of this network."),
        "show": _("All attributes."),
    }

    def validate(self):
        '''
        Validates to ensure that segmentation_id is not there for flat
        network type.
        '''
        super(ProviderNet, self).validate()

        if (self.properties.get(self.PROVIDER_SEGMENTATION_ID) and
                self.properties.get(self.PROVIDER_NETWORK_TYPE) != 'vlan'):
            msg = _('segmentation_id not allowed for flat network type.')
            raise exception.StackValidationFailed(message=msg)

    @staticmethod
    def add_provider_extension(props, key):
        props['provider:' + key] = props.pop(key)

    @staticmethod
    def prepare_provider_properties(self, props):
        self.add_provider_extension(props, self.PROVIDER_NETWORK_TYPE)

        self.add_provider_extension(props, self.PROVIDER_PHYSICAL_NETWORK)

        if self.PROVIDER_SEGMENTATION_ID in props.keys():
            self.add_provider_extension(props, self.PROVIDER_SEGMENTATION_ID)

    def handle_create(self):
        '''
        Adds 'provider:' extension to the required properties during create.
        '''
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        self.prepare_provider_properties(self, props)

        prov_net = self.neutron().create_network({'network': props})['network']
        self.resource_id_set(prov_net['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        '''
        Adds 'provider:' extension to the required properties during update.
        '''
        props = self.prepare_update_properties(json_snippet)

        self.prepare_provider_properties(self, props)

        self.neutron().update_network(self.resource_id, {'network': props})


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::ProviderNet': ProviderNet,
    }
