# Copyright 2018 Ericsson
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
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class L2GatewayConnection(neutron.NeutronResource):
    """A resource for managing Neutron L2 Gateway Connections.

    The L2 Gateway Connection provides a mapping to connect a Neutron network
    to a L2 Gateway on a particular segmentation ID.
    """

    required_service_extension = 'l2-gateway-connection'

    entity = 'l2_gateway_connection'

    support_status = support.SupportStatus(version='12.0.0')

    PROPERTIES = (
        L2_GATEWAY_ID, NETWORK_ID, SEGMENTATION_ID,
    ) = (
        'l2_gateway_id', 'network_id', 'segmentation_id',
    )

    properties_schema = {
        L2_GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying a id of the l2gateway resource.'),
            required=True
        ),
        NETWORK_ID: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying a id of the network resource '
              'to connect to the l2gateway.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.network')
            ],
        ),
        SEGMENTATION_ID: properties.Schema(
            properties.Schema.STRING,
            _('A string specifying a segmentation id for the interface '
              'on the l2gateway.'),
        ),
    }

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        l2gwc = self.client().create_l2_gateway_connection(
            {'l2_gateway_connection': props})['l2_gateway_connection']

        self.resource_id_set(l2gwc['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
            self.client().delete_l2_gateway_connection(self.resource_id)


def resource_mapping():
    return {
        'OS::Neutron::L2GatewayConnection': L2GatewayConnection,
    }
