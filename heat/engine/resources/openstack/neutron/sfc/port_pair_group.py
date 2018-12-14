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
from heat.engine import translation


class PortPairGroup(neutron.NeutronResource):
    """Heat Template Resource for networking-sfc port-pair-group.

    Multiple port-pairs may be included in a port-pair-group to allow the
    specification of a set of functionally equivalent Service Functions that
    can be be used for load distribution.
    """

    support_status = support.SupportStatus(
        version='8.0.0',
        status=support.UNSUPPORTED)

    required_service_extension = 'sfc'

    PROPERTIES = (
        NAME, DESCRIPTION, PORT_PAIRS,
    ) = (
        'name', 'description', 'port_pairs',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the Port Pair Group.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the Port Pair Group.'),
            update_allowed=True
        ),
        PORT_PAIRS: properties.Schema(
            properties.Schema.LIST,
            _('A list of Port Pair IDs or names to apply.'),
            required=True,
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                _('Port Pair ID or name .'),
                constraints=[
                    constraints.CustomConstraint('neutron.port_pair')
                ]
            )
        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.PORT_PAIRS],
                client_plugin=self.client_plugin(),
                finder='resolve_ext_resource',
                entity='port_pair'
            )
        ]

    def _show_resource(self):
        return self.client_plugin().show_ext_resource('port_pair_group',
                                                      self.resource_id)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        port_pair_group = self.client_plugin().create_ext_resource(
            'port_pair_group', props)
        self.resource_id_set(port_pair_group['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client_plugin().update_ext_resource(
                'port_pair_group',
                prop_diff,
                self.resource_id)

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
            self.client_plugin().delete_ext_resource('port_pair_group',
                                                     self.resource_id)


def resource_mapping():
    return {
        'OS::Neutron::PortPairGroup': PortPairGroup,
    }
