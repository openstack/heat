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

from oslo_log import log as logging
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import function

LOG = logging.getLogger(__name__)


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

    def get_value_absolute_path(self, full_value_name=False):
        path = []
        if self.value_name:
            if full_value_name:
                path.extend(self.translation_path[:-1])
            path.append(self.value_name)
        elif self.value_path:
            path.extend(self.value_path)

        if self.custom_value_path:
            path.extend(self.custom_value_path)
        return path


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
        self._ignore_resolve_error = False
        self._deleted_props = []
        self._replaced_props = []

    def set_rules(self, rules, client_resolve=True,
                  ignore_resolve_error=False):
        if not rules:
            return

        self._rules = {}
        self.store_translated_values = client_resolve
        self._ignore_resolve_error = ignore_resolve_error
        for rule in rules:
            if not client_resolve and rule.rule == TranslationRule.RESOLVE:
                continue
            key = '.'.join(rule.translation_path)
            self._rules.setdefault(key, set()).add(rule)

            if rule.rule == TranslationRule.DELETE:
                self._deleted_props.append(key)
            if rule.rule == TranslationRule.REPLACE:
                path = '.'.join(rule.get_value_absolute_path(True))
                self._replaced_props.append(path)

    def is_deleted(self, key):
        return (self.is_active and
                self.cast_key_to_rule(key) in self._deleted_props)

    def is_replaced(self, key):
        return (self.is_active and
                self.cast_key_to_rule(key) in self._replaced_props)

    def cast_key_to_rule(self, key):
        return '.'.join([item for item in key.split('.')
                         if not item.isdigit()])

    def has_translation(self, key):
        key = self.cast_key_to_rule(key)
        return (self.is_active and
                (key in self._rules or key in self.resolved_translations))

    def translate(self, key, prop_value=None, prop_data=None, validate=False):
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

            if rule.rule == TranslationRule.REPLACE:
                result = self.replace(key, rule, result, prop_data, validate)

            if rule.rule == TranslationRule.ADD:
                result = self.add(key, rule, result, prop_data, validate)

            if rule.rule == TranslationRule.RESOLVE:
                resolved_value = resolve_and_find(result,
                                                  rule.client_plugin,
                                                  rule.finder,
                                                  rule.entity,
                                                  self._ignore_resolve_error)
                if self.store_translated_values:
                    self.resolved_translations[key] = resolved_value
                result = resolved_value

        return result

    def add(self, key, add_rule, prop_value=None, prop_data=None,
            validate=False):
        value_path = add_rule.get_value_absolute_path()
        if prop_value is None:
            prop_value = []

        if not isinstance(prop_value, list):
            raise ValueError(_('Incorrect translation rule using - cannot '
                               'resolve Add rule for non-list translation '
                               'value "%s".') % key)

        translation_value = prop_value
        if add_rule.value:
            translation_value.extend(add_rule.value)
        elif value_path:
            if self.has_translation('.'.join(value_path)):
                self.translate('.'.join(value_path),
                               prop_data=prop_data)
            self.is_active = False
            value = get_value(value_path,
                              prop_data if add_rule.value_name else
                              self.properties,
                              validate)
            self.is_active = True
            if value is not None:
                translation_value.extend(value if isinstance(value, list)
                                         else [value])

        if self.store_translated_values:
            self.resolved_translations[key] = translation_value
        return translation_value

    def replace(self, key, replace_rule, prop_value=None, prop_data=None,
                validate=False):
        value = None
        value_path = replace_rule.get_value_absolute_path(full_value_name=True)
        short_path = replace_rule.get_value_absolute_path()

        if value_path:
            if replace_rule.value_name is not None:
                prop_path = key.split('.')[:-1]
                prop_path.extend(short_path)
                prop_path = '.'.join(prop_path)
                subpath = short_path
            else:
                prop_path = '.'.join(value_path)
                subpath = value_path
            props = prop_data if replace_rule.value_name else self.properties
            self.is_active = False
            value = get_value(subpath, props, validate)
            self.is_active = True

            if self.has_translation(prop_path):
                self.translate(prop_path, value, prop_data=prop_data)

            if value and prop_value:
                raise exception.StackValidationFailed(
                    message=_('Cannot define the following properties at '
                              'the same time: %s') % ', '.join(
                        [self.cast_key_to_rule(key), '.'.join(value_path)]))
        elif replace_rule.value is not None:
            value = replace_rule.value

        result = value if value is not None else prop_value
        if self.store_translated_values:
            self.resolved_translations[key] = result
            if value_path:
                if replace_rule.value_name:
                    value_path = (key.split('.')[:-1] + short_path)
                self.resolved_translations['.'.join(value_path)] = None
        return result


def get_value(path, props, validate=False):
    if not props:
        return None

    key = path[0]
    if isinstance(props, dict):
        prop = props.get(key)
    else:
        prop = props._get_property_value(key, validate)
    if len(path[1:]) == 0:
        return prop
    elif prop is None:
        return None
    elif isinstance(prop, list):
        values = []
        for item in prop:
            values.append(get_value(path[1:], item))
        return values
    elif isinstance(prop, dict):
        return get_value(path[1:], prop)


def resolve_and_find(value, cplugin, finder, entity=None,
                     ignore_resolve_error=False):
    if isinstance(value, function.Function):
        value = function.resolve(value)
    if value:
        if isinstance(value, list):
            resolved_value = []
            for item in value:
                resolved_value.append(resolve_and_find(item,
                                                       cplugin,
                                                       finder,
                                                       entity,
                                                       ignore_resolve_error))
            return resolved_value
        finder = getattr(cplugin, finder)
        try:
            if entity:
                return finder(entity, value)
            else:
                return finder(value)
        except Exception as ex:
            if ignore_resolve_error:
                LOG.info("Ignoring error in RESOLVE translation: %s",
                         six.text_type(ex))
                return value
            raise
