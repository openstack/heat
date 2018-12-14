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


class PortPair(neutron.NeutronResource):
    """A resource for neutron networking-sfc port-pair.

    This plug-in requires networking-sfc>=1.0.0. So to enable this
    plug-in, install this library and restart the heat-engine.

    A Port Pair represents a service function instance. The ingress port and
    the egress port of the service function may be specified. If a service
    function has one bidirectional port, the ingress port has the same value
    as the egress port.
    """

    support_status = support.SupportStatus(
        version='7.0.0',
        status=support.UNSUPPORTED)

    PROPERTIES = (
        NAME, DESCRIPTION, INGRESS, EGRESS,
        SERVICE_FUNCTION_PARAMETERS,
        ) = (
        'name', 'description', 'ingress', 'egress',
        'service_function_parameters',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name for the Port Pair.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the Port Pair.'),
            update_allowed=True
        ),
        INGRESS: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the ingress neutron port.'),
            constraints=[constraints.CustomConstraint('neutron.port')],
            required=True,
        ),
        EGRESS: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the egress neutron port.'),
            constraints=[constraints.CustomConstraint('neutron.port')],
            required=True,
        ),
        SERVICE_FUNCTION_PARAMETERS: properties.Schema(
            properties.Schema.MAP,
            _('Dictionary of service function parameter. Currently '
              'only correlation=None is supported.'),
            default={'correlation': None},
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.INGRESS],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_PORT
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.EGRESS],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_PORT
            )
        ]

    def _show_resource(self):
        return self.client_plugin().show_ext_resource('port_pair',
                                                      self.resource_id)

    def handle_create(self):
        props = self.prepare_properties(self.properties,
                                        self.physical_resource_name())
        props['ingress'] = props.get(self.INGRESS)
        props['egress'] = props.get(self.EGRESS)
        port_pair = self.client_plugin().create_ext_resource('port_pair',
                                                             props)
        self.resource_id_set(port_pair['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client_plugin().update_ext_resource('port_pair', prop_diff,
                                                     self.resource_id)

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
                self.client_plugin().delete_ext_resource('port_pair',
                                                         self.resource_id)


def resource_mapping():
    return {
        'OS::Neutron::PortPair': PortPair,
    }
