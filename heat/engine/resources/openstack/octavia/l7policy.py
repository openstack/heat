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
from heat.engine.resources.openstack.octavia import octavia_base
from heat.engine import translation


class L7Policy(octavia_base.OctaviaBase):
    """A resource for managing octavia L7Policies.

    This resource manages L7Policies, which represent a collection of L7Rules.
    L7Policy holds the action that should be performed when the rules are
    matched (Redirect to Pool, Redirect to URL, Reject). L7Policy holds a
    Listener id, so a Listener can evaluate a collection of L7Policies.
    L7Policy will return True when all of the L7Rules that belong
    to this L7Policy are matched. L7Policies under a specific Listener are
    ordered and the first l7Policy that returns a match will be executed.
    When none of the policies match the request gets forwarded to
    listener.default_pool_id.
    """

    PROPERTIES = (
        NAME, DESCRIPTION, ADMIN_STATE_UP, ACTION,
        REDIRECT_POOL, REDIRECT_URL, POSITION, LISTENER
    ) = (
        'name', 'description', 'admin_state_up', 'action',
        'redirect_pool', 'redirect_url', 'position', 'listener'
    )

    L7ACTIONS = (
        REJECT, REDIRECT_TO_POOL, REDIRECT_TO_URL
    ) = (
        'REJECT', 'REDIRECT_TO_POOL', 'REDIRECT_TO_URL'
    )

    ATTRIBUTES = (RULES_ATTR) = ('rules')

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the policy.'),
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the policy.'),
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of the policy.'),
            default=True,
            update_allowed=True
        ),
        ACTION: properties.Schema(
            properties.Schema.STRING,
            _('Action type of the policy.'),
            required=True,
            constraints=[constraints.AllowedValues(L7ACTIONS)],
            update_allowed=True
        ),
        REDIRECT_POOL: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the pool for REDIRECT_TO_POOL action type.'),
            constraints=[
                constraints.CustomConstraint('octavia.pool')
            ],
            update_allowed=True
        ),
        REDIRECT_URL: properties.Schema(
            properties.Schema.STRING,
            _('URL for REDIRECT_TO_URL action type. '
              'This should be a valid URL string.'),
            update_allowed=True
        ),
        POSITION: properties.Schema(
            properties.Schema.NUMBER,
            _('L7 policy position in ordered policies list. This must be '
              'an integer starting from 1. If not specified, policy will be '
              'placed at the tail of existing policies list.'),
            constraints=[constraints.Range(min=1)],
            update_allowed=True
        ),
        LISTENER: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the listener this policy belongs to.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('octavia.listener')
            ]
        ),
    }

    attributes_schema = {
        RULES_ATTR: attributes.Schema(
            _('L7Rules associated with this policy.'),
            type=attributes.Schema.LIST
        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LISTENER],
                client_plugin=self.client_plugin(),
                finder='get_listener',
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.REDIRECT_POOL],
                client_plugin=self.client_plugin(),
                finder='get_pool',
            ),
        ]

    def validate(self):
        super(L7Policy, self).validate()
        if (self.properties[self.ACTION] == self.REJECT and
                (self.properties[self.REDIRECT_POOL] is not None or
                 self.properties[self.REDIRECT_URL] is not None)):
            msg = (_('Properties %(pool)s and %(url)s are not required when '
                     '%(action)s type is set to %(action_type)s.') %
                   {'pool': self.REDIRECT_POOL,
                    'url': self.REDIRECT_URL,
                    'action': self.ACTION,
                    'action_type': self.REJECT})
            raise exception.StackValidationFailed(message=msg)

        if self.properties[self.ACTION] == self.REDIRECT_TO_POOL:
            if self.properties[self.REDIRECT_URL] is not None:
                raise exception.ResourcePropertyValueDependency(
                    prop1=self.REDIRECT_URL,
                    prop2=self.ACTION,
                    value=self.REDIRECT_TO_URL)
            if self.properties[self.REDIRECT_POOL] is None:
                msg = (_('Property %(pool)s is required when %(action)s '
                         'type is set to %(action_type)s.') %
                       {'pool': self.REDIRECT_POOL,
                        'action': self.ACTION,
                        'action_type': self.REDIRECT_TO_POOL})
                raise exception.StackValidationFailed(message=msg)

        if self.properties[self.ACTION] == self.REDIRECT_TO_URL:
            if self.properties[self.REDIRECT_POOL] is not None:
                raise exception.ResourcePropertyValueDependency(
                    prop1=self.REDIRECT_POOL,
                    prop2=self.ACTION,
                    value=self.REDIRECT_TO_POOL)
            if self.properties[self.REDIRECT_URL] is None:
                msg = (_('Property %(url)s is required when %(action)s '
                         'type is set to %(action_type)s.') %
                       {'url': self.REDIRECT_URL,
                        'action': self.ACTION,
                        'action_type': self.REDIRECT_TO_URL})
                raise exception.StackValidationFailed(message=msg)

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items()
                     if v is not None)
        if self.NAME not in props:
            props[self.NAME] = self.physical_resource_name()
        props['listener_id'] = props.pop(self.LISTENER)
        if self.REDIRECT_POOL in props:
            props['redirect_pool_id'] = props.pop(self.REDIRECT_POOL)
        return props

    def _resource_create(self, properties):
        return self.client().l7policy_create(
            json={'l7policy': properties})['l7policy']

    def _resource_update(self, prop_diff):
        if self.REDIRECT_POOL in prop_diff:
            prop_diff['redirect_pool_id'] = prop_diff.pop(self.REDIRECT_POOL)
        self.client().l7policy_set(
            self.resource_id, json={'l7policy': prop_diff})

    def _resource_delete(self):
        self.client().l7policy_delete(self.resource_id)

    def _show_resource(self):
        return self.client().l7policy_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::L7Policy': L7Policy
    }
