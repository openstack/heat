
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
from heat.engine import clients
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.neutron import neutron
from heat.openstack.common import log as logging

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

logger = logging.getLogger(__name__)


class NetworkGateway(neutron.NeutronResource):
    '''
    A resource for the Network Gateway resource in Neutron Network Gateway.
    '''

    PROPERTIES = (
        NAME, DEVICES, CONNECTIONS,
    ) = (
        'name', 'devices', 'connections',
    )

    _DEVICES_KEYS = (
        ID, INTERFACE_NAME,
    ) = (
        'id', 'interface_name',
    )

    _CONNECTIONS_KEYS = (
        NETWORK_ID, SEGMENTATION_TYPE, SEGMENTATION_ID,
    ) = (
        'network_id', 'segmentation_type', 'segmentation_id',
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
                        description=_(
                            'The id of internal network to connect on '
                            'the network gateway.'),
                        required=True
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
        "default": _("A boolean value of default flag."),
        "show": _("All attributes.")
    }

    update_allowed_keys = ('Properties',)

    def _show_resource(self):
        return self.neutron().show_network_gateway(
            self.resource_id)['network_gateway']

    def validate(self):
        '''
        Validate any of the provided params
        '''
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
        ret = self.neutron().create_network_gateway(
            {'network_gateway': props})['network_gateway']

        for connection in connections:
            self.neutron().connect_network_gateway(
                ret['id'], connection
            )

        self.resource_id_set(ret['id'])

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()

        connections = self.properties[self.CONNECTIONS]
        for connection in connections:
            try:
                client.disconnect_network_gateway(
                    self.resource_id, connection
                )
            except NeutronClientException as ex:
                self._handle_not_found_exception(ex)

        try:
            client.delete_network_gateway(self.resource_id)
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return self._delete_task()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)
        connections = props.pop(self.CONNECTIONS)

        if self.DEVICES in prop_diff:
            self.handle_delete()
            self.properties.data.update(props)
            self.handle_create()
            return
        else:
            props.pop(self.DEVICES, None)

        if self.NAME in prop_diff:
            self.neutron().update_network_gateway(
                self.resource_id, {'network_gateway': props})

        if self.CONNECTIONS in prop_diff:
            for connection in self.properties[self.CONNECTIONS]:
                try:
                    self.neutron().disconnect_network_gateway(
                        self.resource_id, connection
                    )
                except NeutronClientException as ex:
                    self._handle_not_found_exception(ex)
            for connection in connections:
                self.neutron().connect_network_gateway(
                    self.resource_id, connection
                )


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::NetworkGateway': NetworkGateway,
    }
