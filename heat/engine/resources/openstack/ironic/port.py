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
from heat.engine import resource
from heat.engine import support
from heat.engine import translation


class Port(resource.Resource):
    """A resource that creates a ironic port.

    Node UUID and physical hardware address for the Port (MAC address in
    most cases) are needed (all Ports must be associated to a Node when
    created).
    """

    support_status = support.SupportStatus(version='13.0.0')

    default_client_name = 'ironic'

    entity = 'port'

    PROPERTIES = (
        NODE, ADDRESS, PORTGROUP, LOCAL_LINK_CONNECTION, PXE_ENABLED,
        PHYSICAL_NETWORK, EXTRA, IS_SMARTNIC,
    ) = (
        'node', 'address', 'portgroup', 'local_link_connection', 'pxe_enabled',
        'physical_network', 'extra', 'is_smartnic',
    )
    PROPERTIES_MIN_SUPPORT_VERSION = (
        (PXE_ENABLED, 1.19),
        (LOCAL_LINK_CONNECTION, 1.191),
        (PORTGROUP, 1.24), (PHYSICAL_NETWORK, 1.34),
        (IS_SMARTNIC, 1.53)
    )

    ATTRIBUTES = (
        ADDRESS_ATTR, NODE_UUID_ATTR, PORTGROUP_UUID_ATTR,
        LOCAL_LINK_CONNECTION_ATTR, PXE_ENABLED_ATTR, PHYSICAL_NETWORK_ATTR,
        INTERNAL_INFO_ATTR, EXTRA_ATTR, IS_SMARTNIC_ATTR,
    ) = (
        'address', 'node_uuid', 'portgroup_uuid',
        'local_link_connection', 'pxe_enabled', 'physical_network',
        'internal_info', 'extra', 'is_smartnic',
    )
    attributes_schema = {
        ADDRESS_ATTR: attributes.Schema(
            _('Physical hardware address of this network Port, typically the '
              'hardware MAC address.'),
            type=attributes.Schema.STRING
        ),
        NODE_UUID_ATTR: attributes.Schema(
            _('UUID of the Node this resource belongs to.'),
            type=attributes.Schema.STRING
        ),
        PORTGROUP_UUID_ATTR: attributes.Schema(
            _('UUID of the Portgroup this resource belongs to.'),
            type=attributes.Schema.STRING
        ),
        LOCAL_LINK_CONNECTION_ATTR: attributes.Schema(
            _('The Port binding profile. If specified, must contain switch_id '
              '(only a MAC address or an OpenFlow based datapath_id of the '
              'switch are accepted in this field) and port_id (identifier of '
              'the physical port on the switch to which node\'s port is '
              'connected to) fields. switch_info is an optional string field '
              'to be used to store any vendor-specific information.'),
            type=attributes.Schema.MAP
        ),
        PXE_ENABLED_ATTR: attributes.Schema(
            _('Indicates whether PXE is enabled or disabled on the Port.'),
            type=attributes.Schema.BOOLEAN
        ),
        PHYSICAL_NETWORK_ATTR: attributes.Schema(
            _('The name of the physical network to which a port is connected. '
              'May be empty.'),
            type=attributes.Schema.STRING
        ),
        INTERNAL_INFO_ATTR: attributes.Schema(
            _('Internal metadata set and stored by the Port. This field is '
              'read-only.'),
            type=attributes.Schema.MAP
        ),
        EXTRA_ATTR: attributes.Schema(
            _('A set of one or more arbitrary metadata key and value pairs.'),
            type=attributes.Schema.MAP
        ),
        IS_SMARTNIC_ATTR: attributes.Schema(
            _('Indicates whether the Port is a Smart NIC port.'),
            type=attributes.Schema.BOOLEAN
        )}

    properties_schema = {
        NODE: properties.Schema(
            properties.Schema.STRING,
            _('UUID or name of the Node this resource belongs to.'),
            constraints=[
                constraints.CustomConstraint('ironic.node')
            ],
            required=True,
            update_allowed=True
        ),
        ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Physical hardware address of this network Port, typically the '
              'hardware MAC address.'),
            required=True,
            update_allowed=True
        ),
        PORTGROUP: properties.Schema(
            properties.Schema.STRING,
            _('UUID or name of the Portgroup this resource belongs to.'),
            constraints=[
                constraints.CustomConstraint('ironic.portgroup')
            ],
            update_allowed=True,
        ),
        LOCAL_LINK_CONNECTION: properties.Schema(
            properties.Schema.MAP,
            _('The Port binding profile. If specified, must contain switch_id '
              '(only a MAC address or an OpenFlow based datapath_id of the '
              'switch are accepted in this field) and port_id (identifier of '
              'the physical port on the switch to which node\'s port is '
              'connected to) fields. switch_info is an optional string field '
              'to be used to store any vendor-specific information.'),
            update_allowed=True,
        ),
        PXE_ENABLED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Indicates whether PXE is enabled or disabled on the Port.'),
            update_allowed=True,
        ),
        PHYSICAL_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('The name of the physical network to which a port is connected. '
              'May be empty.'),
            update_allowed=True,
        ),
        EXTRA: properties.Schema(
            properties.Schema.MAP,
            _('A set of one or more arbitrary metadata key and value pairs.'),
            update_allowed=True,
        ),
        IS_SMARTNIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Indicates whether the Port is a Smart NIC port.'),
            update_allowed=True,
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.NODE],
                client_plugin=self.client_plugin('ironic'),
                finder='get_node'),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.PORTGROUP],
                client_plugin=self.client_plugin('ironic'),
                finder='get_portgroup'),
        ]

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        port = self.client().port.get(self.resource_id)
        return getattr(port, name, None)

    def _check_supported(self, properties):
        # TODO(ricolin) Implement version support in property schema.
        for k, v in self.PROPERTIES_MIN_SUPPORT_VERSION:
            if k in properties and properties[k] is not None and (
                self.client_plugin().max_microversion < v
            ):
                raise exception.NotSupported(
                    feature="OS::Ironic::Port with %s property" % k)

    def handle_create(self):
        args = dict(self.properties.items())
        self._check_supported(args)
        args['node_uuid'] = args.pop(self.NODE)
        if self.PORTGROUP in args:
            args['portgroup_uuid'] = args.pop(self.PORTGROUP)
        port = self.client().port.create(**args)
        self.resource_id_set(port.uuid)
        return port.uuid

    def check_create_complete(self, id):
        try:
            self.client().port.get(id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return False
        return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self._check_supported(prop_diff)
            if self.NODE in prop_diff:
                prop_diff['node_uuid'] = prop_diff.pop(self.NODE)
            if self.PORTGROUP in prop_diff:
                prop_diff['portgroup_uuid'] = prop_diff.pop(self.PORTGROUP)
            patch = [{'op': 'replace', 'path': '/' + k, 'value': v}
                     for k, v in prop_diff.items()]
            self.client().port.update(self.resource_id, patch)
            return self.resource_id, prop_diff

    def check_delete_complete(self, id):
        if not id:
            return True
        try:
            self.client().port.get(id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            return True
        return False


def resource_mapping():
    return {
        'OS::Ironic::Port': Port,
    }
