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
from heat.engine.cfn import functions as cfn_funcs
from heat.engine import function
from heat.engine.hot import functions as hot_funcs
from heat.engine import properties


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
    """

    RULE_KEYS = (ADD, REPLACE, DELETE) = ('Add', 'Replace', 'Delete')

    def __init__(self, properties, rule, source_path, value=None,
                 value_name=None, value_path=None):
        """Add new rule for translating mechanism.

        :param properties: properties of resource
        :param rule: rule from RULE_KEYS
        :param source_path: list with path to property, which value will be
               affected in rule.
        :param value: value which will be involved in rule
        :param value_name: value_name which used for replacing properties
               inside list-type properties.
        :param value_path: path to value, which should be used for translation.
        """
        self.properties = properties
        self.rule = rule
        self.source_path = source_path
        self.value = value or None
        self.value_name = value_name
        self.value_path = value_path

        self.validate()

    def validate(self):
        if self.rule not in self.RULE_KEYS:
            raise ValueError(_('There is no rule %(rule)s. List of allowed '
                               'rules is: %(rules)s.') % {
                'rule': self.rule,
                'rules': ', '.join(self.RULE_KEYS)})
        elif not isinstance(self.properties, properties.Properties):
            raise ValueError(_('Properties must be Properties type. '
                               'Found %s.') % type(self.properties))
        elif not isinstance(self.source_path, list):
            raise ValueError(_('source_path should be a list with path '
                               'instead of %s.') % type(self.source_path))
        elif len(self.source_path) == 0:
            raise ValueError(_('source_path must be non-empty list with '
                               'path.'))
        elif self.value_name and self.rule != self.REPLACE:
            raise ValueError(_('Use value_name only for replacing list '
                               'elements.'))
        elif self.rule == self.ADD and not isinstance(self.value, list):
            raise ValueError(_('value must be list type when rule is Add.'))

    def execute_rule(self):
        try:
            (source_key, source_data) = self.get_data_from_source_path(
                self.source_path)
            if self.value_path:
                (value_key, value_data) = self.get_data_from_source_path(
                    self.value_path)
                value = (value_data[value_key]
                         if value_data and value_data.get(value_key)
                         else self.value)
            else:
                (value_key, value_data) = None, None
                value = self.value
        except AttributeError:
            return

        if (source_data is None or (self.rule != self.DELETE and
                                    (value is None and
                                     self.value_name is None and
                                     (value_data is None or
                                      value_data.get(value_key) is None)))):
            return

        if self.rule == TranslationRule.ADD:
            if isinstance(source_data, list):
                source_data.extend(value)
            else:
                raise ValueError(_('Add rule must be used only for '
                                   'lists.'))
        elif self.rule == TranslationRule.REPLACE:
            if isinstance(source_data, list):
                for item in source_data:
                    if item.get(self.value_name) and item.get(source_key):
                        raise ValueError(_('Cannot use %(key)s and '
                                           '%(name)s at the same time.')
                                         % dict(key=source_key,
                                                name=self.value_name))
                    elif item.get(self.value_name) is not None:
                        item[source_key] = item[self.value_name]
                        del item[self.value_name]
                    elif value is not None:
                        item[source_key] = value
            else:
                if (source_data and source_data.get(source_key) and
                        value_data and value_data.get(value_key)):
                    raise ValueError(_('Cannot use %(key)s and '
                                       '%(name)s at the same time.')
                                     % dict(key=source_key,
                                            name=value_key))
                source_data[source_key] = value
                # If value defined with value_path, need to delete value_path
                # property data after it's replacing.
                if value_data and value_data.get(value_key):
                    del value_data[value_key]
        elif self.rule == TranslationRule.DELETE:
            if isinstance(source_data, list):
                for item in source_data:
                    if item.get(source_key) is not None:
                        del item[source_key]
            else:
                del source_data[source_key]

    def get_data_from_source_path(self, path):
        def get_props(props, key):
            props = props.get(key)
            if props.schema.schema is not None:
                keys = list(props.schema.schema)
                schemata = dict((k, props.schema.schema[k])
                                for k in keys)
                props = dict((k, properties.Property(s, k))
                             for k, s in schemata.items())
            return props

        def resolve_param(param):
            """Check whether if given item is param and resolve, if it is."""
            # NOTE(prazumovsky): If property uses removed in HOT function,
            # we should not translate it for correct validating and raising
            # validation error.
            if isinstance(param, hot_funcs.Removed):
                raise AttributeError(_('Property uses removed function.'))
            if isinstance(param, (hot_funcs.GetParam, cfn_funcs.ParamRef)):
                return function.resolve(param)
            elif isinstance(param, list):
                return [resolve_param(param_item) for param_item in param]
            else:
                return param

        source_key = path[0]
        data = self.properties.data
        props = self.properties.props
        for key in path:
            if isinstance(data, list):
                source_key = key
            elif data.get(key) is not None:
                # NOTE(prazumovsky): There's no need to resolve other functions
                # because we can translate all function to another path. But if
                # list or map type property equals to get_param function, need
                # to resolve it for correct translating.
                data[key] = resolve_param(data[key])
                if isinstance(data[key], (dict, list)):
                    data = data[key]
                    props = get_props(props, key)
                else:
                    source_key = key
            elif data.get(key) is None:
                if (self.rule == TranslationRule.DELETE or
                        (self.rule == TranslationRule.REPLACE and
                         self.value_name)):
                    return None, None
                elif props.get(key).type() == properties.Schema.LIST:
                    data[key] = []
                elif props.get(key).type() == properties.Schema.MAP:
                    data[key] = {}
                else:
                    source_key = key
                    continue
                data = data.get(key)
                props = get_props(props, key)
        return source_key, data
