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

import functools
import six

from oslo_utils import encodeutils

from heat.common import exception
from heat.common.i18n import _
from heat.engine.cfn import functions as cfn_funcs
from heat.engine import function
from heat.engine.hot import functions as hot_funcs
from heat.engine import properties


@functools.total_ordering
class TranslationRule(object):
    """Translating mechanism one properties to another.

    Mechanism uses list of rules, each defines by this class, and can be
    executed. Working principe: during resource creating after properties
    defining resource take list of rules, specified by method
    translation_rules, which should be overloaded for each resource, if it's
    needed, and execute each rule using translate_properties method. Next
    operations are allowed:

    - ADD. This rule allows to add some value to list-type properties. Only
           list-type values can be added to such properties. Using for other
           cases is prohibited and will be returned with error.
    - REPLACE. This rule allows to replace some property value to another. Used
           for all types of properties. Note, that if property has list type,
           then value will be replaced for all elements of list, where it
           needed. If element in such property must be replaced by value of
           another element of this property, value_name must be defined.
    - DELETE. This rule allows to delete some property. If property has list
           type, then deleting affects value in all list elements.
    - RESOLVE. This rule allows to resolve some property using client and
           the finder function. Finders may require an additional entity key.
    """

    RULE_KEYS = (ADD, REPLACE,
                 DELETE, RESOLVE) = ('Add', 'Replace',
                                     'Delete', 'Resolve')

    def __lt__(self, other):
        rules = [TranslationRule.ADD,
                 TranslationRule.REPLACE,
                 TranslationRule.RESOLVE,
                 TranslationRule.DELETE]
        idx1 = rules.index(self.rule)
        idx2 = rules.index(other.rule)
        return idx1 < idx2

    def __init__(self, properties, rule, translation_path, value=None,
                 value_name=None, value_path=None, client_plugin=None,
                 finder=None, entity=None, custom_value_path=None):
        """Add new rule for translating mechanism.

        :param properties: properties of resource
        :param rule: rule from RULE_KEYS
        :param translation_path: list with path to property, which value will
               be affected in rule.
        :param value: value which will be involved in rule
        :param value_name: value_name which used for replacing properties
               inside list-type properties.
        :param value_path: path to value, which should be used for translation.
        :param client_plugin: client plugin that would be used to resolve
        :param finder: finder method of the client plugin
        :param entity: some generic finders require an entity to resolve ex.
               neutron finder function.
        :param custom_value_path: list-type value path to translate property,
               which has no schema.
        """
        self.properties = properties
        self.rule = rule
        self.translation_path = translation_path
        self.value = value or None
        self.value_name = value_name
        self.value_path = value_path
        self.client_plugin = client_plugin
        self.finder = finder
        self.entity = entity
        self.custom_value_path = custom_value_path

        self.validate()

    def validate(self):
        if self.rule not in self.RULE_KEYS:
            raise ValueError(_('There is no rule %(rule)s. List of allowed '
                               'rules is: %(rules)s.') % {
                'rule': self.rule,
                'rules': ', '.join(self.RULE_KEYS)})
        if not isinstance(self.properties, properties.Properties):
            raise ValueError(_('Properties must be Properties type. '
                               'Found %s.') % type(self.properties))

        if (not isinstance(self.translation_path, list) or
                len(self.translation_path) == 0):
            raise ValueError(_('"translation_path" should be non-empty list '
                               'with path to translate.'))

        args = [self.value_path is not None, self.value is not None,
                self.value_name is not None]
        if args.count(True) > 1:
            raise ValueError(_('"value_path", "value" and "value_name" are '
                               'mutually exclusive and cannot be specified '
                               'at the same time.'))

        if (self.rule == self.ADD and self.value is not None and
                not isinstance(self.value, list)):
            raise ValueError(_('"value" must be list type when rule is Add.'))

        if (self.rule == self.RESOLVE and
                not (self.client_plugin or self.finder)):
            raise ValueError(_('"client_plugin" and "finder" should be '
                               'specified for %s rule') % self.RESOLVE)

    def execute_rule(self, client_resolve=True):
        try:
            self._prepare_data(self.properties.data, self.translation_path,
                               self.properties.props)
            if self.value_path:
                if self.custom_value_path:
                    self.value_path.extend(self.custom_value_path)
                self._prepare_data(self.properties.data, self.value_path,
                                   self.properties.props)
                (value_key,
                 value_data) = self.translate_property(self.value_path,
                                                       self.properties.data,
                                                       return_value=True)
                value = (value_data[value_key]
                         if value_data and value_data.get(value_key)
                         else self.value)
            else:
                (value_key, value_data) = None, None
                value = self.value
        except AttributeError:
            return

        self.translate_property(self.translation_path, self.properties.data,
                                value=value, value_data=value_data,
                                value_key=value_key,
                                client_resolve=client_resolve)

    def _prepare_data(self, data, path, props):
        def get_props(props, key):
            props = props.get(key)
            if props.schema.schema is not None:
                keys = list(props.schema.schema)
                schemata = dict((k, props.schema.schema[k])
                                for k in keys)
                props = dict((k, properties.Property(s, k))
                             for k, s in schemata.items())
                if set(props.keys()) == set('*'):
                    return get_props(props, '*')
            return props

        if not path:
            return
        current_key = path[0]
        if data.get(current_key) is None:
            if (self.rule in (TranslationRule.DELETE,
                              TranslationRule.RESOLVE) or
                    (self.rule == TranslationRule.REPLACE and
                     self.value_name is not None)):
                return
            data_type = props.get(current_key).type()
            if data_type == properties.Schema.LIST:
                data[current_key] = []
            if data_type == properties.Schema.MAP:
                data[current_key] = {}
            return
        data[current_key] = self._resolve_param(data.get(current_key))
        if isinstance(data[current_key], list):
            for item in data[current_key]:
                self._prepare_data(item, path[1:],
                                   get_props(props, current_key))
        elif isinstance(data[current_key], dict):
            self._prepare_data(data[current_key], path[1:],
                               get_props(props, current_key))

    def _exec_action(self, key, data, value=None, value_key=None,
                     value_data=None, client_resolve=True):
        if self.rule == TranslationRule.ADD:
            self._exec_add(key, data, value)
        elif self.rule == TranslationRule.REPLACE:
            self._exec_replace(key, data, value_key, value_data, value)
        elif self.rule == TranslationRule.RESOLVE and client_resolve:
            self._exec_resolve(key, data)
        elif self.rule == TranslationRule.DELETE:
            self._exec_delete(key, data)

    def _resolve_param(self, param):
        """Check whether given item is param and resolve, if it is."""
        if isinstance(param, (hot_funcs.GetParam, cfn_funcs.ParamRef)):
            try:
                return function.resolve(param)
            except exception.UserParameterMissing as ex:
                # We can't resolve parameter now. Abort translation.
                err_msg = encodeutils.exception_to_unicode(ex)
                raise AttributeError(
                    _('Can not resolve parameter '
                      'due to: %s') % err_msg)
        elif isinstance(param, list):
            return [self._resolve_param(param_item) for param_item in param]
        else:
            return param

    def resolve_custom_value_path(self, translation_data, translation_key):
        new_value = translation_data[self.value_name]
        for key in self.custom_value_path[:-1]:
            if isinstance(new_value, (list, six.string_types)):
                raise ValueError(
                    _('Incorrectly specified custom_value_path - '
                      'cannot pull out required value from '
                      'data of %s type.') % type(new_value))
            if new_value.get(key) is None:
                return
            new_value = self._resolve_param(new_value[key])
        resolved_value = self._resolve_param(
            new_value.get(self.custom_value_path[-1]))
        if resolved_value is None:
            return
        if self.rule == self.REPLACE:
            translation_data[translation_key] = resolved_value
            del new_value[self.custom_value_path[-1]]
        elif self.rule == self.ADD:
            if isinstance(resolved_value, list):
                translation_data[translation_key].extend(resolved_value)
            else:
                translation_data[translation_key].append(resolved_value)

    def translate_property(self, path, data, return_value=False, value=None,
                           value_data=None, value_key=None,
                           client_resolve=True):
        if isinstance(data, function.Function):
            if return_value:
                raise AttributeError('No chance to translate value due to '
                                     'value is function. Skip translation.')
            return
        current_key = path[0]
        if len(path) <= 1:
            if return_value:
                return current_key, data
            else:
                self._exec_action(current_key, data,
                                  value=value, value_data=value_data,
                                  value_key=value_key,
                                  client_resolve=client_resolve)
            return
        if data.get(current_key) is None:
            return
        elif isinstance(data[current_key], list):
            for item in data[current_key]:
                if return_value:
                    # Until there's no reasonable solution for cases of using
                    # one list for value and another list for destination,
                    # error would be raised.
                    msg = _('Cannot use value_path for properties inside '
                            'list-type properties')
                    raise ValueError(msg)
                else:
                    self.translate_property(path[1:], item,
                                            return_value=return_value,
                                            value=value, value_data=value_data,
                                            value_key=value_key,
                                            client_resolve=client_resolve)
        else:
            return self.translate_property(path[1:], data[current_key],
                                           return_value=return_value,
                                           value=value, value_data=value_data,
                                           value_key=value_key,
                                           client_resolve=client_resolve)

    def _exec_add(self, translation_key, translation_data, value):
        if not isinstance(translation_data[translation_key], list):
            raise ValueError(_('Add rule must be used only for '
                               'lists.'))
        if value is not None:
            translation_data[translation_key].extend(value)
        elif (self.value_name is not None and
              translation_data.get(self.value_name) is not None):
            if self.custom_value_path:
                self.resolve_custom_value_path(translation_data,
                                               translation_key)
            elif isinstance(translation_data[self.value_name], list):
                translation_data[translation_key].extend(
                    translation_data[self.value_name])
            else:
                translation_data[translation_key].append(
                    translation_data[self.value_name])

    def _exec_replace(self, translation_key, translation_data,
                      value_key, value_data, value):
        value_ind = None
        if translation_data and translation_data.get(translation_key):
            if value_data and value_data.get(value_key):
                value_ind = value_key
            elif translation_data.get(self.value_name) is not None:
                value_ind = self.value_name
                if self.custom_value_path is not None:
                    data = translation_data.get(self.value_name)
                    for key in self.custom_value_path:
                        data = data.get(key)
                        if data is None:
                            value_ind = None
                            break

        if value_ind is not None:
            raise exception.ResourcePropertyConflict(props=[translation_key,
                                                            value_ind])
        if value is not None:
            translation_data[translation_key] = value
        elif (self.value_name is not None and
                translation_data.get(self.value_name) is not None):
            if self.custom_value_path:
                self.resolve_custom_value_path(translation_data,
                                               translation_key)
            else:
                translation_data[
                    translation_key] = translation_data[self.value_name]
                del translation_data[self.value_name]

        # If value defined with value_path, need to delete value_path
        # property data after it's replacing.
        if value_data and value_data.get(value_key):
            del value_data[value_key]

    def _exec_resolve(self, translation_key, translation_data):

        def resolve_and_find(translation_value):
            if isinstance(translation_value, function.Function):
                translation_value = function.resolve(translation_value)
            if translation_value:
                if isinstance(translation_value, list):
                    resolved_value = []
                    for item in translation_value:
                        resolved_value.append(resolve_and_find(item))
                    return resolved_value
                finder = getattr(self.client_plugin, self.finder)
                if self.entity:
                    return finder(self.entity, translation_value)
                else:
                    return finder(translation_value)

        if isinstance(translation_data, list):
            for item in translation_data:
                translation_value = item.get(translation_key)
                resolved_value = resolve_and_find(translation_value)
                if resolved_value is not None:
                    item[translation_key] = resolved_value
        else:
            translation_value = translation_data.get(translation_key)
            resolved_value = resolve_and_find(translation_value)
            if resolved_value is not None:
                translation_data[translation_key] = resolved_value

    def _exec_delete(self, translation_key, translation_data):
        if isinstance(translation_data, list):
            for item in translation_data:
                if item.get(translation_key) is not None:
                    del item[translation_key]
        elif translation_data.get(translation_key) is not None:
            del translation_data[translation_key]


class Translation(object):
    """Mechanism for translating one properties to other.

    Mechanism allows to handle properties - update deprecated/hidden properties
    to new, resolve values, remove unnecessary. It uses list of TranslationRule
    objects as rules for translation.
    """

    def __init__(self, properties=None):
        """Initialise translation mechanism.

        :param properties: Properties class object to resolve rule pathes.

        :var _rules: store specified rules by set_rules method.
        :var resolves_translations: key-pair dict, where key is string-type
             full path of property, value is a resolved value.
        :var is_active: indicate to not translate property, if property already
             in translation and just tries to get property value. This
             indicator escapes from infinite loop.
        :var store_translated_values: define storing resolved values. Useful
             for validation phase, where not all functions can be resolved
             (``get_attr`` for not created resource, for example).
        """
        self.properties = properties
        self._rules = {}
        self.resolved_translations = {}
        self.is_active = True
        self.store_translated_values = True
        self._deleted_props = []

    def set_rules(self, rules, client_resolve=True):
        if not rules:
            return

        self._rules = {}
        self.store_translated_values = client_resolve
        for rule in rules:
            if not client_resolve and rule.rule == TranslationRule.RESOLVE:
                continue
            key = '.'.join(rule.translation_path)
            self._rules.setdefault(key, set()).add(rule)

            if rule.rule == TranslationRule.DELETE:
                self._deleted_props.append(key)

    def is_deleted(self, key):
        return (self.is_active and
                self.cast_key_to_rule(key) in self._deleted_props)

    def cast_key_to_rule(self, key):
        return '.'.join([item for item in key.split('.')
                         if not item.isdigit()])

    def has_translation(self, key):
        key = self.cast_key_to_rule(key)
        return (self.is_active and
                (key in self._rules or key in self.resolved_translations))

    def translate(self, key, prop_value=None, prop_data=None):
        if key in self.resolved_translations:
            return self.resolved_translations[key]

        result = prop_value
        if self._rules.get(self.cast_key_to_rule(key)) is None:
            return result
        for rule in sorted(self._rules.get(self.cast_key_to_rule(key))):
            if rule.rule == TranslationRule.DELETE:
                if self.store_translated_values:
                    self.resolved_translations[key] = None
                result = None

        return result
