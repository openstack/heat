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


class FlowClassifier(neutron.NeutronResource):
    """"Heat Template Resource for networking-sfc flow-classifier.

    This resource used to select the traffic that can access the service chain.
    Traffic that matches any flow classifier will be directed to the first
    port in the chain.
    """

    support_status = support.SupportStatus(
        version='8.0.0',
        status=support.UNSUPPORTED)

    PROPERTIES = (
        NAME, DESCRIPTION, PROTOCOL, ETHERTYPE,
        SOURCE_IP_PREFIX, DESTINATION_IP_PREFIX, SOURCE_PORT_RANGE_MIN,
        SOURCE_PORT_RANGE_MAX, DESTINATION_PORT_RANGE_MIN,
        DESTINATION_PORT_RANGE_MAX, LOGICAL_SOURCE_PORT,
        LOGICAL_DESTINATION_PORT, L7_PARAMETERS,
    ) = (
        'name', 'description', 'protocol', 'ethertype',
        'source_ip_prefix', 'destination_ip_prefix',
        'source_port_range_min', 'source_port_range_max',
        'destination_port_range_min', 'destination_port_range_max',
        'logical_source_port', 'logical_destination_port', 'l7_parameters',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the Flow Classifier.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the Flow Classifier.'),
            update_allowed=True
        ),
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('IP Protocol for the Flow Classifier.'),
            constraints=[
                constraints.AllowedValues(['tcp', 'udp', 'icmp']),
            ],
        ),
        ETHERTYPE: properties.Schema(
            properties.Schema.STRING,
            _('L2 ethertype.'),
            default='IPv4',
            constraints=[
                constraints.AllowedValues(['IPv4', 'IPv6']),
            ],
        ),
        SOURCE_IP_PREFIX: properties.Schema(
            properties.Schema.STRING,
            _('Source IP prefix or subnet.'),
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
        ),
        DESTINATION_IP_PREFIX: properties.Schema(
            properties.Schema.STRING,
            _('Destination IP prefix or subnet.'),
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
        ),
        SOURCE_PORT_RANGE_MIN: properties.Schema(
            properties.Schema.INTEGER,
            _('Source protocol port Minimum.'),
            constraints=[
                constraints.Range(1, 65535)
            ]
        ),
        SOURCE_PORT_RANGE_MAX: properties.Schema(
            properties.Schema.INTEGER,
            _('Source protocol port Maximum.'),
            constraints=[
                constraints.Range(1, 65535)
            ]
        ),
        DESTINATION_PORT_RANGE_MIN: properties.Schema(
            properties.Schema.INTEGER,
            _('Destination protocol port minimum.'),
            constraints=[
                constraints.Range(1, 65535)
            ]
        ),
        DESTINATION_PORT_RANGE_MAX: properties.Schema(
            properties.Schema.INTEGER,
            _('Destination protocol port maximum.'),
            constraints=[
                constraints.Range(1, 65535)
            ]
        ),
        LOGICAL_SOURCE_PORT: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the neutron source port.'),
            constraints=[
                constraints.CustomConstraint('neutron.port')
            ]
        ),
        LOGICAL_DESTINATION_PORT: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the neutron destination port.'),
            constraints=[
                constraints.CustomConstraint('neutron.port')
            ]
        ),
        L7_PARAMETERS: properties.Schema(
            properties.Schema.MAP,
            _('Dictionary of L7-parameters.'),
            support_status=support.SupportStatus(
                status=support.UNSUPPORTED,
                message=_('Currently, no value is supported for this option.'),
            ),
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LOGICAL_SOURCE_PORT],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_PORT
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LOGICAL_DESTINATION_PORT],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_PORT
            )
        ]

    def _show_resource(self):
        return self.client_plugin().show_ext_resource('flow_classifier',
                                                      self.resource_id)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        flow_classifier = self.client_plugin().create_ext_resource(
            'flow_classifier', props)
        self.resource_id_set(flow_classifier['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client_plugin().update_ext_resource('flow_classifier',
                                                     prop_diff,
                                                     self.resource_id)

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
                self.client_plugin().delete_ext_resource('flow_classifier',
                                                         self.resource_id)


def resource_mapping():
    return {
        'OS::Neutron::FlowClassifier': FlowClassifier,
    }
