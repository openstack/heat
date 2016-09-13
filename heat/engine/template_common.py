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
from heat.engine import output
from heat.engine import template


class CommonTemplate(template.Template):
    """A class of the common implementation for HOT and CFN templates.

    This is *not* a stable interface, and any third-parties who create derived
    classes from it do so at their own risk.
    """

    @classmethod
    def validate_resource_key_type(cls, key, valid_types, typename,
                                   rsrc_name, rsrc_data):
        """Validate the type of the value provided for a specific resource key.

        Used in _validate_resource_definition() to validate correctness of
        user input data.
        """
        if key in rsrc_data:
            if not isinstance(rsrc_data[key], valid_types):
                args = {'name': rsrc_name, 'key': key,
                        'typename': typename}
                message = _('Resource %(name)s %(key)s type '
                            'must be %(typename)s') % args
                raise TypeError(message)
            return True
        else:
            return False

    def _validate_resource_definition(self, name, data):
        """Validate a resource definition snippet given the parsed data."""

        if not self.validate_resource_key_type(self.RES_TYPE,
                                               six.string_types,
                                               'string',
                                               name,
                                               data):
            args = {'name': name, 'type_key': self.RES_TYPE}
            msg = _('Resource %(name)s is missing "%(type_key)s"') % args
            raise KeyError(msg)

        self.validate_resource_key_type(
            self.RES_PROPERTIES,
            (collections.Mapping, function.Function),
            'object', name, data)
        self.validate_resource_key_type(
            self.RES_METADATA,
            (collections.Mapping, function.Function),
            'object', name, data)
        self.validate_resource_key_type(
            self.RES_DEPENDS_ON,
            collections.Sequence,
            'list or string', name, data)
        self.validate_resource_key_type(
            self.RES_DELETION_POLICY,
            (six.string_types, function.Function),
            'string', name, data)
        self.validate_resource_key_type(
            self.RES_UPDATE_POLICY,
            (collections.Mapping, function.Function),
            'object', name, data)
        self.validate_resource_key_type(
            self.RES_DESCRIPTION,
            six.string_types,
            'string', name, data)

    def _resolve_conditions(self, stack):
        cd_snippet = self._get_condition_definitions()
        result = {}
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

    def _get_condition_definitions(self):
        """Return the condition definitions of template."""
        return {}

    def conditions(self, stack):
        if self._conditions is None:
            resolved_cds = self._resolve_conditions(stack)
            if resolved_cds:
                for cd_key, cd_value in six.iteritems(resolved_cds):
                    if not isinstance(cd_value, bool):
                        raise exception.InvalidConditionDefinition(
                            cd=cd_key,
                            definition=cd_value)

            self._conditions = resolved_cds

        return self._conditions

    def outputs(self, stack):
        conditions = Conditions(self.conditions(stack))

        outputs = self.t.get(self.OUTPUTS) or {}

        def get_outputs():
            for key, val in outputs.items():
                if not isinstance(val, collections.Mapping):
                    message = _('Output definitions must be a map. Found a '
                                '%s instead') % type(val).__name__
                    raise exception.StackValidationFailed(
                        error='Output validation error',
                        path=[self.OUTPUTS, key],
                        message=message)

                if self.OUTPUT_VALUE not in val:
                    message = _('Each output definition must contain '
                                'a %s key.') % self.OUTPUT_VALUE
                    raise exception.StackValidationFailed(
                        error='Output validation error',
                        path=[self.OUTPUTS, key],
                        message=message)

                description = val.get(self.OUTPUT_DESCRIPTION)

                if hasattr(self, 'OUTPUT_CONDITION'):
                    cond_name = val.get(self.OUTPUT_CONDITION)
                    path = '.'.join([self.OUTPUTS,
                                     key,
                                     self.OUTPUT_CONDITION])
                    if not conditions.is_enabled(cond_name, path):
                        yield key, output.OutputDefinition(key, None,
                                                           description)
                        continue

                value_def = self.parse(stack, val[self.OUTPUT_VALUE],
                                       path='.'.join([self.OUTPUTS, key,
                                                      self.OUTPUT_VALUE]))

                yield key, output.OutputDefinition(key, value_def, description)

        return dict(get_outputs())


class Conditions(object):
    def __init__(self, conditions_dict):
        self._conditions = conditions_dict

    def is_enabled(self, condition_name, path):
        if condition_name is None:
            return True

        if condition_name not in self._conditions:
            raise exception.InvalidConditionReference(cd=condition_name,
                                                      path=path)

        return self._conditions[condition_name]
