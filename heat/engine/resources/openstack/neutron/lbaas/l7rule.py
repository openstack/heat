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


class L7Rule(neutron.NeutronResource):
    """A resource for managing LBaaS v2 L7Rules.

    This resource manages Neutron-LBaaS v2 L7Rules, which represent
    a set of attributes that defines which part of the request should
    be matched and how it should be matched.
    """

    support_status = support.SupportStatus(version='7.0.0')

    required_service_extension = 'lbaasv2'

    entity = 'lbaas_l7rule'

    res_info_key = 'rule'

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

    def __init__(self, name, definition, stack):
        super(L7Rule, self).__init__(name, definition, stack)
        self._l7p_id = None
        self._lb_id = None

    @property
    def l7policy_id(self):
        client_plugin = self.client_plugin()
        if self._l7p_id is None:
            self._l7p_id = client_plugin.find_resourceid_by_name_or_id(
                client_plugin.RES_TYPE_LB_L7POLICY,
                self.properties[self.L7POLICY])
        return self._l7p_id

    @property
    def lb_id(self):
        if self._lb_id is None:
            policy = self.client().show_lbaas_l7policy(
                self.l7policy_id)['l7policy']
            listener_id = policy['listener_id']
            listener = self.client().show_listener(listener_id)['listener']
            self._lb_id = listener['loadbalancers'][0]['id']
        return self._lb_id

    def _check_lb_status(self):
        return self.client_plugin().check_lb_status(self.lb_id)

    def validate(self):
        res = super(L7Rule, self).validate()
        if res:
            return res

        if (self.properties[self.TYPE] in (self.HEADER, self.COOKIE) and
                self.properties[self.KEY] is None):
            msg = (_('Property %(key)s is missing. '
                     'This property should be specified for '
                     'rules of %(header)s and %(cookie)s types.') %
                   {'key': self.KEY,
                    'header': self.HEADER,
                    'cookie': self.COOKIE})
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        rule_args = dict((k, v) for k, v in self.properties.items()
                         if k != self.L7POLICY)
        return rule_args

    def check_create_complete(self, rule_args):
        if self.resource_id is None:
            try:
                l7rule = self.client().create_lbaas_l7rule(
                    self.l7policy_id,
                    {'rule': rule_args})['rule']
                self.resource_id_set(l7rule['id'])
            except Exception as ex:
                if self.client_plugin().is_invalid(ex):
                    return False
                raise

        return self._check_lb_status()

    def _res_get_args(self):
        return [self.resource_id, self.l7policy_id]

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self._update_called = False
        if (prop_diff.get(self.TYPE) in (self.COOKIE, self.HEADER) and
                prop_diff.get(self.KEY) is None):
            prop_diff[self.KEY] = tmpl_diff['Properties'].get(self.KEY)

        return prop_diff

    def check_update_complete(self, prop_diff):
        if not prop_diff:
            return True

        if not self._update_called:
            try:
                self.client().update_lbaas_l7rule(
                    self.resource_id,
                    self.l7policy_id,
                    {'rule': prop_diff})
                self._update_called = True
            except Exception as ex:
                if self.client_plugin().is_invalid(ex):
                    return False
                raise

        return self._check_lb_status()

    def handle_delete(self):
        self._delete_called = False

    def check_delete_complete(self, data):
        if self.resource_id is None:
            return True

        if not self._delete_called:
            try:
                self.client().delete_lbaas_l7rule(
                    self.resource_id,
                    self.l7policy_id)
                self._delete_called = True
            except Exception as ex:
                if self.client_plugin().is_invalid(ex):
                    return False
                elif self.client_plugin().is_not_found(ex):
                    return True
                raise

        return self._check_lb_status()


def resource_mapping():
    return {
        'OS::Neutron::LBaaS::L7Rule': L7Rule
    }
