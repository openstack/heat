#
# Copyright 2013 NTT Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class NetworkGateway(neutron.NeutronResource):
    """Network Gateway resource in Neutron Network Gateway.

    Resource for connecting internal networks with specified devices.
    """

    support_status = support.SupportStatus(version='2014.1')

    entity = 'network_gateway'

    PROPERTIES = (
        NAME, DEVICES, CONNECTIONS,
    ) = (
        'name', 'devices', 'connections',
    )

    ATTRIBUTES = (
        DEFAULT,
    ) = (
        'default',
    )

    _DEVICES_KEYS = (
        ID, INTERFACE_NAME,
    ) = (
        'id', 'interface_name',
    )

    _CONNECTIONS_KEYS = (
        NETWORK_ID, NETWORK, SEGMENTATION_TYPE, SEGMENTATION_ID,
    ) = (
        'network_id', 'network', 'segmentation_type', 'segmentation_id',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            description=_('The name of the network gateway.'),
            update_allowed=True
        ),
        DEVICES: properties.Schema(
            properties.Schema.LIST,
            description=_('Device info for this network gateway.'),
            required=True,
            constraints=[constraints.Length(min=1)],
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    ID: properties.Schema(
                        properties.Schema.STRING,
                        description=_('The device id for the network '
                                      'gateway.'),
                        required=True
                    ),
                    INTERFACE_NAME: properties.Schema(
                        properties.Schema.STRING,
                        description=_('The interface name for the '
                                      'network gateway.'),
                        required=True
                    )
                }
            )
        ),
        CONNECTIONS: properties.Schema(
            properties.Schema.LIST,
            description=_('Connection info for this network gateway.'),
            default={},
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NETWORK_ID: properties.Schema(
                        properties.Schema.STRING,
                        support_status=support.SupportStatus(
                            status=support.HIDDEN,
                            message=_('Use property %s.') % NETWORK,
                            version='5.0.0',
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
                        description=_(
                            'The internal network to connect on '
                            'the network gateway.'),
                        support_status=support.SupportStatus(version='2014.2'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('neutron.network')
                        ],
                    ),
                    SEGMENTATION_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        description=_(
                            'L2 segmentation strategy on the external '
                            'side of the network gateway.'),
                        default='flat',
                        constraints=[constraints.AllowedValues(
                            ('flat', 'vlan'))]
                    ),
                    SEGMENTATION_ID: properties.Schema(
                        properties.Schema.INTEGER,
                        description=_(
                            'The id for L2 segment on the external side '
                            'of the network gateway. Must be specified '
                            'when using vlan.'),
                        constraints=[constraints.Range(0, 4094)]
                    )
                }
            )
        )
    }

    attributes_schema = {
        DEFAULT: attributes.Schema(
            _("A boolean value of default flag."),
            type=attributes.Schema.STRING
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.CONNECTIONS, self.NETWORK],
                value_name=self.NETWORK_ID
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.CONNECTIONS, self.NETWORK],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_NETWORK
            )
        ]

    def validate(self):
        """Validate any of the provided params."""
        super(NetworkGateway, self).validate()
        connections = self.properties[self.CONNECTIONS]

        for connection in connections:
            segmentation_type = connection[self.SEGMENTATION_TYPE]
            segmentation_id = connection.get(self.SEGMENTATION_ID)

            if segmentation_type == 'vlan' and segmentation_id is None:
                msg = _("segmentation_id must be specified for using vlan")
                raise exception.StackValidationFailed(message=msg)

            if segmentation_type == 'flat' and segmentation_id:
                msg = _(
                    "segmentation_id cannot be specified except 0 for "
                    "using flat")
                raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        connections = props.pop(self.CONNECTIONS)
        ret = self.client().create_network_gateway(
            {'network_gateway': props})['network_gateway']

        self.resource_id_set(ret['id'])

        for connection in connections:
            if self.NETWORK in connection:
                connection['network_id'] = connection.pop(self.NETWORK)
            self.client().connect_network_gateway(
                ret['id'], connection
            )

    def handle_delete(self):
        if not self.resource_id:
            return

        connections = self.properties[self.CONNECTIONS]
        for connection in connections:
            with self.client_plugin().ignore_not_found:
                if self.NETWORK in connection:
                    connection['network_id'] = connection.pop(self.NETWORK)
                self.client().disconnect_network_gateway(
                    self.resource_id, connection
                )
        try:
            self.client().delete_network_gateway(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        connections = None
        if self.CONNECTIONS in prop_diff:
            connections = prop_diff.pop(self.CONNECTIONS)

        if self.DEVICES in prop_diff:
            self.handle_delete()
            self.properties.data.update(prop_diff)
            self.handle_create()
            return

        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client().update_network_gateway(
                self.resource_id, {'network_gateway': prop_diff})

        if connections:
            for connection in self.properties[self.CONNECTIONS]:
                with self.client_plugin().ignore_not_found:
                    if self.NETWORK in connection:
                        connection[
                            'network_id'] = connection.pop(self.NETWORK)
                    self.client().disconnect_network_gateway(
                        self.resource_id, connection
                    )
            for connection in connections:
                if self.NETWORK in connection:
                    connection['network_id'] = connection.pop(self.NETWORK)
                self.client().connect_network_gateway(
                    self.resource_id, connection
                )


def resource_mapping():
    return {
        'OS::Neutron::NetworkGateway': NetworkGateway,
    }
