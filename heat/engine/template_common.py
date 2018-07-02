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
import functools
import weakref

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

    def __init__(self, template, template_id=None, files=None, env=None):
        super(CommonTemplate, self).__init__(template, template_id=template_id,
                                             files=files, env=env)
        self._conditions_cache = None, None

    @classmethod
    def _parse_resource_field(cls, key, valid_types, typename,
                              rsrc_name, rsrc_data, parse_func):
        """Parse a field in a resource definition.

        :param key: The name of the key
        :param valid_types: Valid types for the parsed output
        :param typename: Description of valid type to include in error output
        :param rsrc_name: The resource name
        :param rsrc_data: The unparsed resource definition data
        :param parse_func: A function to parse the data, which takes the
            contents of the field and its path in the template as arguments.
        """
        if key in rsrc_data:
            data = parse_func(rsrc_data[key], '.'.join([cls.RESOURCES,
                                                        rsrc_name,
                                                        key]))
            if not isinstance(data, valid_types):
                args = {'name': rsrc_name, 'key': key,
                        'typename': typename}
                message = _('Resource %(name)s %(key)s type '
                            'must be %(typename)s') % args
                raise TypeError(message)
            return data
        else:
            return None

    def _rsrc_defn_args(self, stack, name, data):
        if self.RES_TYPE not in data:
            args = {'name': name, 'type_key': self.RES_TYPE}
            msg = _('Resource %(name)s is missing "%(type_key)s"') % args
            raise KeyError(msg)

        parse = functools.partial(self.parse, stack)

        def no_parse(field, path):
            return field

        yield ('resource_type',
               self._parse_resource_field(self.RES_TYPE,
                                          six.string_types, 'string',
                                          name, data, parse))

        yield ('properties',
               self._parse_resource_field(self.RES_PROPERTIES,
                                          (collections.Mapping,
                                           function.Function), 'object',
                                          name, data, parse))

        yield ('metadata',
               self._parse_resource_field(self.RES_METADATA,
                                          (collections.Mapping,
                                           function.Function), 'object',
                                          name, data, parse))

        depends = self._parse_resource_field(self.RES_DEPENDS_ON,
                                             collections.Sequence,
                                             'list or string',
                                             name, data, no_parse)
        if isinstance(depends, six.string_types):
            depends = [depends]
        elif depends:
            for dep in depends:
                if not isinstance(dep, six.string_types):
                    msg = _('Resource %(name)s %(key)s '
                            'must be a list of strings') % {
                                'name': name, 'key': self.RES_DEPENDS_ON}
                    raise exception.StackValidationFailed(message=msg)

        yield 'depends', depends

        del_policy = self._parse_resource_field(self.RES_DELETION_POLICY,
                                                (six.string_types,
                                                 function.Function),
                                                'string',
                                                name, data, parse)
        deletion_policy = function.resolve(del_policy)
        if deletion_policy is not None:
            if deletion_policy not in self.deletion_policies:
                msg = _('Invalid deletion policy "%s"') % deletion_policy
                raise exception.StackValidationFailed(message=msg)
            else:
                deletion_policy = self.deletion_policies[deletion_policy]
        yield 'deletion_policy', deletion_policy

        yield ('update_policy',
               self._parse_resource_field(self.RES_UPDATE_POLICY,
                                          (collections.Mapping,
                                           function.Function), 'object',
                                          name, data, parse))

        yield ('description',
               self._parse_resource_field(self.RES_DESCRIPTION,
                                          six.string_types, 'string',
                                          name, data, no_parse))

    def _get_condition_definitions(self):
        """Return the condition definitions of template."""
        return {}

    def conditions(self, stack):
        get_cache_stack, cached_conds = self._conditions_cache
        if (cached_conds is not None and
                get_cache_stack is not None and
                get_cache_stack() is stack):
            return cached_conds

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
        conds = conditions.Conditions(parsed)

        get_cache_stack = weakref.ref(stack) if stack is not None else None
        self._conditions_cache = get_cache_stack, conds
        return conds

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
                    path = [self.OUTPUTS, key, self.OUTPUT_CONDITION]
                    cond = self.parse_condition(stack,
                                                val.get(self.OUTPUT_CONDITION),
                                                '.'.join(path))
                    try:
                        enabled = conds.is_enabled(function.resolve(cond))
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
