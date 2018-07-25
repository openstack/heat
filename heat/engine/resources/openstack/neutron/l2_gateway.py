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

import collections
import six

from heat.common.i18n import _
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class L2Gateway(neutron.NeutronResource):
    """A resource for managing Neutron L2 Gateways.

    The are a number of use cases that can be addressed by an L2 Gateway API.
    Most notably in cloud computing environments, a typical use case is
    bridging the virtual with the physical. Translate this to Neutron and the
    OpenStack world, and this means relying on L2 Gateway capabilities to
    extend Neutron logical (overlay) networks into physical (provider)
    networks that are outside the OpenStack realm.
    """

    required_service_extension = 'l2-gateway'

    entity = 'l2_gateway'

    support_status = support.SupportStatus(version='12.0.0')

    PROPERTIES = (
        NAME, DEVICES,
    ) = (
        'name', 'devices',
    )

    _DEVICE_KEYS = (
        DEVICE_NAME, INTERFACES,
    ) = (
        'device_name', 'interfaces',
    )

    _INTERFACE_KEYS = (
        INTERFACE_NAME, SEGMENTATION_ID,
    ) = (
        'name', 'segmentation_id',
    )

    _interface_schema = {
        INTERFACE_NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the interface on the gateway device.'),
            required=True
        ),
        SEGMENTATION_ID: properties.Schema(
            properties.Schema.LIST,
            _('A list of segmentation ids of the interface.')
        ),
    }

    _device_schema = {
        DEVICE_NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the gateway device.'),
            required=True
        ),
        INTERFACES: properties.Schema(
            properties.Schema.LIST,
            _('List of gateway device interfaces.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema=_interface_schema
            ),
            required=True
        )
    }

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('A symbolic name for the l2-gateway, '
              'which is not required to be unique.'),
            required=True,
            update_allowed=True
        ),
        DEVICES: properties.Schema(
            properties.Schema.LIST,
            _('List of gateway devices.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema=_device_schema
            ),
            required=True,
            update_allowed=True
        ),
    }

    @staticmethod
    def _remove_none_value_props(props):
        if isinstance(props, collections.Mapping):
            return dict((k, L2Gateway._remove_none_value_props(v)) for k, v
                        in props.items() if v is not None)
        elif (isinstance(props, collections.Sequence) and
              not isinstance(props, six.string_types)):
            return list(L2Gateway._remove_none_value_props(l) for l in props
                        if l is not None)
        return props

    @staticmethod
    def prepare_properties(properties, name):
        # Overrides method from base class NeutronResource to ensure None
        # values are removed from all levels of value_specs.

        # TODO(neatherweb): move this recursive check for None to
        # prepare_properties in NeutronResource
        props = L2Gateway._remove_none_value_props(dict(properties))

        if 'name' in properties:
            props.setdefault('name', name)

        return props

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        l2gw = self.client().create_l2_gateway(
            {'l2_gateway': props})['l2_gateway']
        self.resource_id_set(l2gw['id'])

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
            self.client().delete_l2_gateway(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            prop_diff = L2Gateway._remove_none_value_props(prop_diff)
            self.client().update_l2_gateway(
                self.resource_id, {'l2_gateway': prop_diff})


def resource_mapping():
    return {
        'OS::Neutron::L2Gateway': L2Gateway,
    }
