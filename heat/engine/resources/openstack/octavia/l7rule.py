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
from heat.engine.resources.openstack.octavia import octavia_base
from heat.engine import translation


class L7Rule(octavia_base.OctaviaBase):
    """A resource for managing octavia L7Rules.

    This resource manages L7Rules, which represent a set of attributes
    that defines which part of the request should be matched and how
    it should be matched.
    """

    PROPERTIES = (
        ADMIN_STATE_UP, L7POLICY, TYPE, COMPARE_TYPE,
        INVERT, KEY, VALUE
    ) = (
        'admin_state_up', 'l7policy', 'type', 'compare_type',
        'invert', 'key', 'value'
    )

    L7RULE_TYPES = (
        HOST_NAME, PATH, FILE_TYPE, HEADER, COOKIE
    ) = (
        'HOST_NAME', 'PATH', 'FILE_TYPE', 'HEADER', 'COOKIE'
    )

    L7COMPARE_TYPES = (
        REGEX, STARTS_WITH, ENDS_WITH, CONTAINS, EQUAL_TO
    ) = (
        'REGEX', 'STARTS_WITH', 'ENDS_WITH', 'CONTAINS', 'EQUAL_TO'
    )

    properties_schema = {
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of the rule.'),
            default=True,
            update_allowed=True
        ),
        L7POLICY: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of L7 policy this rule belongs to.'),
            constraints=[
                constraints.CustomConstraint('octavia.l7policy')
            ],
            required=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Rule type.'),
            constraints=[constraints.AllowedValues(L7RULE_TYPES)],
            update_allowed=True,
            required=True
        ),
        COMPARE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Rule compare type.'),
            constraints=[constraints.AllowedValues(L7COMPARE_TYPES)],
            update_allowed=True,
            required=True
        ),
        INVERT: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Invert the compare type.'),
            default=False,
            update_allowed=True
        ),
        KEY: properties.Schema(
            properties.Schema.STRING,
            _('Key to compare. Relevant for HEADER and COOKIE types only.'),
            update_allowed=True
        ),
        VALUE: properties.Schema(
            properties.Schema.STRING,
            _('Value to compare.'),
            update_allowed=True,
            required=True
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.L7POLICY],
                client_plugin=self.client_plugin(),
                finder='get_l7policy',
            )
        ]

    def validate(self):
        super(L7Rule, self).validate()
        if (self.properties[self.TYPE] in (self.HEADER, self.COOKIE) and
                self.properties[self.KEY] is None):
            msg = (_('Property %(key)s is missing. '
                     'This property should be specified for '
                     'rules of %(header)s and %(cookie)s types.') %
                   {'key': self.KEY,
                    'header': self.HEADER,
                    'cookie': self.COOKIE})
            raise exception.StackValidationFailed(message=msg)

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items()
                     if v is not None)
        props.pop(self.L7POLICY)
        return props

    def _resource_create(self, properties):
        return self.client().l7rule_create(self.properties[self.L7POLICY],
                                           json={'rule': properties})['rule']

    def _resource_update(self, prop_diff):
        self.client().l7rule_set(self.resource_id,
                                 self.properties[self.L7POLICY],
                                 json={'rule': prop_diff})

    def _resource_delete(self):
        self.client().l7rule_delete(self.resource_id,
                                    self.properties[self.L7POLICY])

    def _show_resource(self):
        return self.client().l7rule_show(self.resource_id,
                                         self.properties[self.L7POLICY])


def resource_mapping():
    return {
        'OS::Octavia::L7Rule': L7Rule
    }
