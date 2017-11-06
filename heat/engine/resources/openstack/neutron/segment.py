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
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class Segment(neutron.NeutronResource):
    """A resource for Neutron Segment.

    This requires enabling the segments service plug-in by appending
    'segments' to the list of service_plugins in the neutron.conf.

    The default policy usage of this resource is limited to
    administrators only.
    """

    required_service_extension = 'segment'

    support_status = support.SupportStatus(version='9.0.0')

    NETWORK_TYPES = [LOCAL, VLAN, VXLAN,
                     GRE, GENEVE, FLAT] = ['local', 'vlan', 'vxlan',
                                           'gre', 'geneve', 'flat']
    PROPERTIES = (
        NETWORK, NETWORK_TYPE, PHYSICAL_NETWORK, SEGMENTATION_ID,
        NAME, DESCRIPTION
    ) = (
        'network', 'network_type', 'physical_network', 'segmentation_id',
        'name', 'description'
    )

    properties_schema = {
        NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('The name/id of network to associate with this segment.'),
            constraints=[constraints.CustomConstraint('neutron.network')],
            required=True
        ),
        NETWORK_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of network to associate with this segment.'),
            constraints=[
                constraints.AllowedValues(NETWORK_TYPES),
            ],
            required=True
        ),
        PHYSICAL_NETWORK: properties.Schema(
            properties.Schema.STRING,
            _('Name of physical network to associate with this segment.'),
        ),
        SEGMENTATION_ID: properties.Schema(
            properties.Schema.INTEGER,
            _('Segmentation ID for this segment.'),
            constraints=[
                constraints.Range(min=1),
            ],
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the segment.'),
            update_allowed=True,
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the segment.'),
            update_allowed=True,
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.NETWORK],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_NETWORK
            )]

    def validate(self):
        super(Segment, self).validate()
        phys_network = self.properties[self.PHYSICAL_NETWORK]
        network_type = self.properties[self.NETWORK_TYPE]
        seg_id = self.properties[self.SEGMENTATION_ID]

        msg_fmt = _('%(prop)s is required for %(type)s provider network.')
        if network_type in [self.FLAT, self.VLAN] and phys_network is None:
            msg = msg_fmt % {'prop': self.PHYSICAL_NETWORK,
                             'type': network_type}
            raise exception.StackValidationFailed(message=msg)

        if network_type == self.VLAN and seg_id is None:
            msg = msg_fmt % {'prop': self.SEGMENTATION_ID,
                             'type': network_type}
            raise exception.StackValidationFailed(message=msg)

        msg_fmt = _('%(prop)s is prohibited for %(type)s provider network.')
        if network_type in [self.LOCAL, self.FLAT] and seg_id is not None:
            msg = msg_fmt % {'prop': self.SEGMENTATION_ID,
                             'type': network_type}
            raise exception.StackValidationFailed(message=msg)

        tunnel_types = [self.VXLAN, self.GRE, self.GENEVE]
        if network_type in tunnel_types and phys_network is not None:
            msg = msg_fmt % {'prop': self.PHYSICAL_NETWORK,
                             'type': network_type}
            raise exception.StackValidationFailed(message=msg)

        if network_type == self.VLAN and seg_id > 4094:
            msg = _('Up to 4094 VLAN network segments can exist '
                    'on each physical_network.')
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        props['network_id'] = props.pop(self.NETWORK)
        segment = self.client('openstack').network.create_segment(**props)
        self.resource_id_set(segment.id)

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin('openstack').ignore_not_found:
            self.client('openstack').network.delete_segment(self.resource_id)

    def needs_replace_failed(self):
        if not self.resource_id:
            return True

        with self.client_plugin('openstack').ignore_not_found:
            self._show_resource()
            return False

        return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client('openstack').network.update_segment(
                self.resource_id, **prop_diff)

    def _show_resource(self):
        return self.client('openstack').network.get_segment(
            self.resource_id).to_dict()


def resource_mapping():
    return {
        'OS::Neutron::Segment': Segment
    }
