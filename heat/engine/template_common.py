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

import collections

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import function
from heat.engine import template


class CommonTemplate(template.Template):
    """A class of the common implementation for HOT and CFN templates."""

    def validate_resource_definition(self, name, data):
        allowed_keys = set(self._RESOURCE_KEYS)

        if not self.validate_resource_key_type(self.RES_TYPE,
                                               six.string_types,
                                               'string',
                                               allowed_keys,
                                               name,
                                               data):
            args = {'name': name, 'type_key': self.RES_TYPE}
            msg = _('Resource %(name)s is missing "%(type_key)s"') % args
            raise KeyError(msg)

        self.validate_resource_key_type(
            self.RES_PROPERTIES,
            (collections.Mapping, function.Function),
            'object', allowed_keys, name, data)
        self.validate_resource_key_type(
            self.RES_METADATA,
            (collections.Mapping, function.Function),
            'object', allowed_keys, name, data)
        self.validate_resource_key_type(
            self.RES_DEPENDS_ON,
            collections.Sequence,
            'list or string', allowed_keys, name, data)
        self.validate_resource_key_type(
            self.RES_DELETION_POLICY,
            (six.string_types, function.Function),
            'string', allowed_keys, name, data)
        self.validate_resource_key_type(
            self.RES_UPDATE_POLICY,
            (collections.Mapping, function.Function),
            'object', allowed_keys, name, data)
        self.validate_resource_key_type(
            self.RES_DESCRIPTION,
            six.string_types,
            'string', allowed_keys, name, data)

    def validate_resource_definitions(self, stack):
        """Check section's type of ResourceDefinitions."""

        resources = self.t.get(self.RESOURCES) or {}

        try:
            for name, snippet in resources.items():
                path = '.'.join([self.RESOURCES, name])
                data = self.parse(stack, snippet, path)
                self.validate_resource_definition(name, data)
        except (TypeError, ValueError, KeyError) as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))

    def validate_condition_definitions(self, stack):
        """Check conditions section."""

        resolved_cds = self.resolve_conditions(stack)
        if resolved_cds:
            for cd_key, cd_value in six.iteritems(resolved_cds):
                if not isinstance(cd_value, bool):
                    raise exception.InvalidConditionDefinition(
                        cd=cd_key,
                        definition=cd_value)

    def resolve_conditions(self, stack):
        cd_snippet = self.get_condition_definitions()
        result = {}
        if cd_snippet:
            for cd_key, cd_value in six.iteritems(cd_snippet):
                # hasn't been resolved yet
                if not isinstance(cd_value, bool):
                    condition_func = self.parse_condition(
                        stack, cd_value)
                    resolved_cd_value = function.resolve(condition_func)
                    result[cd_key] = resolved_cd_value
                else:
                    result[cd_key] = cd_value

        return result

    def get_condition_definitions(self):
        """Return the condition definitions of template."""
        return {}

    def has_condition_section(self, snippet):
        return False

    def get_res_condition(self, stack, res_data, res_name):
        """Return the value of condition referenced by resource."""

        path = ''
        if self.has_condition_section(res_data):
            path = '.'.join([res_name, self.RES_CONDITION])

        return self.get_condition(res_data, stack, path)

    def get_condition(self, snippet, stack, path=''):
        # if specify condition return the resolved condition value,
        # true or false if don't specify condition, return true
        if self.has_condition_section(snippet):
            cd_key = snippet[self.CONDITION]
            cds = self.conditions(stack)
            if cd_key not in cds:
                raise exception.InvalidConditionReference(
                    cd=cd_key, path=path)
            cd = cds[cd_key]
            return cd

        return True

    def conditions(self, stack):
        if self._conditions is None:
            self._conditions = self.resolve_conditions(stack)

        return self._conditions
