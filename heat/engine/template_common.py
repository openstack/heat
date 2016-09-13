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
from heat.engine import conditions
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

    def _get_condition_definitions(self):
        """Return the condition definitions of template."""
        return {}

    def conditions(self, stack):
        if self._conditions is None:
            raw_defs = self._get_condition_definitions()
            if not isinstance(raw_defs, collections.Mapping):
                message = _('Condition definitions must be a map. Found a '
                            '%s instead') % type(raw_defs).__name__
                raise exception.StackValidationFailed(
                    error='Conditions validation error',
                    message=message)

            parsed = {n: self.parse_condition(stack, c,
                                              '.'.join([self.CONDITIONS, n]))
                      for n, c in raw_defs.items()}
            self._conditions = conditions.Conditions(parsed)

        return self._conditions

    def outputs(self, stack):
        conds = self.conditions(stack)

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
                    try:
                        enabled = conds.is_enabled(cond_name)
                    except ValueError as exc:
                        path = [self.OUTPUTS, key, self.OUTPUT_CONDITION]
                        message = six.text_type(exc)
                        raise exception.StackValidationFailed(path=path,
                                                              message=message)

                    if not enabled:
                        yield key, output.OutputDefinition(key, None,
                                                           description)
                        continue

                value_def = self.parse(stack, val[self.OUTPUT_VALUE],
                                       path='.'.join([self.OUTPUTS, key,
                                                      self.OUTPUT_VALUE]))

                yield key, output.OutputDefinition(key, value_def, description)

        return dict(get_outputs())
