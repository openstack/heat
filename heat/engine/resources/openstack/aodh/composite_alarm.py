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
from heat.engine.resources import alarm_base
from heat.engine import support


class CompositeAlarm(alarm_base.BaseAlarm):
    """A resource that implements Aodh composite alarm.

    Allows to specify multiple rules when creating a composite alarm,
    and the rules combined with logical operators: and, or.
    """

    alarm_type = 'composite'

    support_status = support.SupportStatus(version='8.0.0')

    PROPERTIES = (
        COMPOSITE_RULE, COMPOSITE_OPERATOR, RULES,
    ) = (
        'composite_rule', 'operator', 'rules',
    )

    composite_rule_schema = {
        COMPOSITE_OPERATOR: properties.Schema(
            properties.Schema.STRING,
            _('The operator indicates how to combine the rules.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.AllowedValues(['or', 'and'])
            ]
        ),
        RULES: properties.Schema(
            properties.Schema.LIST,
            _('Rules list. Basic threshold/gnocchi rules and nested dict '
              'which combine threshold/gnocchi rules by "and" or "or" are '
              'allowed. For example, the form is like: [RULE1, RULE2, '
              '{"and": [RULE3, RULE4]}], the basic threshold/gnocchi '
              'rules must include a "type" field.'),
            required=True,
            update_allowed=True,
            constraints=[
                constraints.Length(min=2)
            ]
        ),
    }

    properties_schema = {
        COMPOSITE_RULE: properties.Schema(
            properties.Schema.MAP,
            _('Composite threshold rules in JSON format.'),
            required=True,
            update_allowed=True,
            schema=composite_rule_schema
        )
    }

    properties_schema.update(alarm_base.common_properties_schema)

    def parse_composite_rule(self, props):
        composite_rule = props.get(self.COMPOSITE_RULE)
        operator = composite_rule[self.COMPOSITE_OPERATOR]
        rules = composite_rule[self.RULES]
        props[self.COMPOSITE_RULE] = {operator: rules}

    def handle_create(self):
        props = self.actions_to_urls(self.properties)
        self.parse_composite_rule(props)
        props['name'] = self.physical_resource_name()
        props['type'] = self.alarm_type

        alarm = self.client().alarm.create(props)
        self.resource_id_set(alarm['alarm_id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            updated_props = self.actions_to_urls(prop_diff)
            if self.COMPOSITE_RULE in prop_diff:
                self.parse_composite_rule(updated_props)
            self.client().alarm.update(self.resource_id, updated_props)


def resource_mapping():
    return {
        'OS::Aodh::CompositeAlarm': CompositeAlarm,
    }
