# Copyright (c) 2016 Huawei Technologies India Pvt Ltd
# All Rights Reserved.
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


class PortChain(neutron.NeutronResource):
    """A resource for neutron networking-sfc.

    This resource used to define the service function path by arranging
    networking-sfc port-pair-groups and set of flow classifiers, to specify
    the classified traffic flows to enter the chain.
    """

    support_status = support.SupportStatus(
        version='8.0.0',
        status=support.UNSUPPORTED)

    required_service_extension = 'sfc'

    PROPERTIES = (
        NAME, DESCRIPTION, PORT_PAIR_GROUPS, FLOW_CLASSIFIERS,
        CHAIN_PARAMETERS,
    ) = (
        'name', 'description', 'port_pair_groups',
        'flow_classifiers', 'chain_parameters',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the Port Chain.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description for the Port Chain.'),
            update_allowed=True
        ),
        PORT_PAIR_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('A list of port pair groups to apply to the Port Chain.'),
            update_allowed=True,
            required=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                _('Port Pair Group ID or Name .'),
                constraints=[
                    constraints.CustomConstraint('neutron.port_pair_group')
                ]
            )
        ),
        FLOW_CLASSIFIERS: properties.Schema(
            properties.Schema.LIST,
            _('A list of flow classifiers to apply to the Port Chain.'),
            default=[],
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.STRING,
                _('Flow Classifier ID or Name .'),
                constraints=[
                    constraints.CustomConstraint('neutron.flow_classifier')
                ]
            )
        ),
        CHAIN_PARAMETERS: properties.Schema(
            properties.Schema.MAP,
            _('Dictionary of chain parameters. Currently, only '
              'correlation=mpls is supported by default.'),
            default={"correlation": "mpls"}
        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.PORT_PAIR_GROUPS],
                client_plugin=self.client_plugin(),
                finder='resolve_ext_resource',
                entity='port_pair_group'
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.FLOW_CLASSIFIERS],
                client_plugin=self.client_plugin(),
                finder='resolve_ext_resource',
                entity='flow_classifier'
            ),
        ]

    def _show_resource(self):
        return self.client_plugin().show_ext_resource('port_chain',
                                                      self.resource_id)

    def handle_create(self):
        props = self.prepare_properties(self.properties,
                                        self.physical_resource_name())
        port_chain = self.client_plugin().create_ext_resource(
            'port_chain', props)
        self.resource_id_set(port_chain['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.prepare_update_properties(prop_diff)
            self.client_plugin().update_ext_resource('port_chain',
                                                     prop_diff,
                                                     self.resource_id)

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
            self.client_plugin().delete_ext_resource('port_chain',
                                                     self.resource_id)


def resource_mapping():
    return {
        'OS::Neutron::PortChain': PortChain,
    }
