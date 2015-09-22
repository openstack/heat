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

from oslo_serialization import jsonutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints as constr
from heat.engine import function
from heat.engine.hot import parameters as hot_param
from heat.engine import parameters
from heat.engine import support

SCHEMA_KEYS = (
    REQUIRED, IMPLEMENTED, DEFAULT, TYPE, SCHEMA,
    ALLOWED_PATTERN, MIN_VALUE, MAX_VALUE, ALLOWED_VALUES,
    MIN_LENGTH, MAX_LENGTH, DESCRIPTION, UPDATE_ALLOWED,
    IMMUTABLE,
) = (
    'Required', 'Implemented', 'Default', 'Type', 'Schema',
    'AllowedPattern', 'MinValue', 'MaxValue', 'AllowedValues',
    'MinLength', 'MaxLength', 'Description', 'UpdateAllowed',
    'Immutable',
)


class Schema(constr.Schema):
    """Schema class for validating resource properties.

    This class is used for defining schema constraints for resource properties.
    It inherits generic validation features from the base Schema class and add
    processing that is specific to resource properties.
    """

    KEYS = (
        TYPE, DESCRIPTION, DEFAULT, SCHEMA, REQUIRED, CONSTRAINTS,
        UPDATE_ALLOWED, IMMUTABLE,
    ) = (
        'type', 'description', 'default', 'schema', 'required', 'constraints',
        'update_allowed', 'immutable',
    )

    def __init__(self, data_type, description=None,
                 default=None, schema=None,
                 required=False, constraints=None,
                 implemented=True,
                 update_allowed=False,
                 immutable=False,
                 support_status=support.SupportStatus(),
                 allow_conversion=False):
        super(Schema, self).__init__(data_type, description, default,
                                     schema, required, constraints)
        self.implemented = implemented
        self.update_allowed = update_allowed
        self.immutable = immutable
        self.support_status = support_status
        self.allow_conversion = allow_conversion
        # validate structural correctness of schema itself
        self.validate()

    @classmethod
    def from_legacy(cls, schema_dict):
        """Return a Property Schema object from a legacy schema dictionary."""

        # Check for fully-fledged Schema objects
        if isinstance(schema_dict, cls):
            return schema_dict

        unknown = [k for k in schema_dict if k not in SCHEMA_KEYS]
        if unknown:
            raise exception.InvalidSchemaError(
                message=_('Unknown key(s) %s') % unknown)

        def constraints():
            def get_num(key):
                val = schema_dict.get(key)
                if val is not None:
                    val = Schema.str_to_num(val)
                return val

            if MIN_VALUE in schema_dict or MAX_VALUE in schema_dict:
                yield constr.Range(get_num(MIN_VALUE), get_num(MAX_VALUE))
            if MIN_LENGTH in schema_dict or MAX_LENGTH in schema_dict:
                yield constr.Length(get_num(MIN_LENGTH), get_num(MAX_LENGTH))
            if ALLOWED_VALUES in schema_dict:
                yield constr.AllowedValues(schema_dict[ALLOWED_VALUES])
            if ALLOWED_PATTERN in schema_dict:
                yield constr.AllowedPattern(schema_dict[ALLOWED_PATTERN])

        try:
            data_type = schema_dict[TYPE]
        except KeyError:
            raise exception.InvalidSchemaError(
                message=_('No %s specified') % TYPE)

        if SCHEMA in schema_dict:
            if data_type == Schema.LIST:
                ss = cls.from_legacy(schema_dict[SCHEMA])
            elif data_type == Schema.MAP:
                schema_dicts = schema_dict[SCHEMA].items()
                ss = dict((n, cls.from_legacy(sd)) for n, sd in schema_dicts)
            else:
                raise exception.InvalidSchemaError(
                    message=_('%(schema)s supplied for %(type)s %(data)s') %
                    dict(schema=SCHEMA, type=TYPE, data=data_type))
        else:
            ss = None

        return cls(data_type,
                   description=schema_dict.get(DESCRIPTION),
                   default=schema_dict.get(DEFAULT),
                   schema=ss,
                   required=schema_dict.get(REQUIRED, False),
                   constraints=list(constraints()),
                   implemented=schema_dict.get(IMPLEMENTED, True),
                   update_allowed=schema_dict.get(UPDATE_ALLOWED, False),
                   immutable=schema_dict.get(IMMUTABLE, False))

    @classmethod
    def from_parameter(cls, param):
        """Return a Property Schema corresponding to a Parameter Schema.

        Convert a parameter schema from a provider template to a property
        Schema for the corresponding resource facade.
        """

        # map param types to property types
        param_type_map = {
            param.STRING: cls.STRING,
            param.NUMBER: cls.NUMBER,
            param.LIST: cls.LIST,
            param.MAP: cls.MAP,
            param.BOOLEAN: cls.BOOLEAN
        }

        # allow_conversion allows slightly more flexible type conversion
        # where property->parameter types don't align, primarily when
        # a json parameter value is passed via a Map property, which requires
        # some coercion to pass strings or lists (which are both valid for
        # Json parameters but not for Map properties).
        allow_conversion = param.type == param.MAP

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(data_type=param_type_map.get(param.type, cls.MAP),
                   description=param.description,
                   required=param.required,
                   constraints=param.constraints,
                   update_allowed=True,
                   immutable=False,
                   allow_conversion=allow_conversion,
                   default=param.default)

    def allowed_param_prop_type(self):
        """Return allowed type of Property Schema converted from parameter.

        Especially, when generating Schema from parameter, Integer Property
        Schema will be supplied by Number parameter.
        """
        param_type_map = {
            self.INTEGER: self.NUMBER,
            self.STRING: self.STRING,
            self.NUMBER: self.NUMBER,
            self.BOOLEAN: self.BOOLEAN,
            self.LIST: self.LIST,
            self.MAP: self.MAP
        }

        return param_type_map[self.type]

    def __getitem__(self, key):
        if key == self.UPDATE_ALLOWED:
            return self.update_allowed
        elif key == self.IMMUTABLE:
            return self.immutable
        else:
            return super(Schema, self).__getitem__(key)


def schemata(schema_dicts):
    """Return dictionary of Schema objects for given dictionary of schemata.

    The input schemata are converted from the legacy (dictionary-based)
    format to Schema objects where necessary.
    """
    return dict((n, Schema.from_legacy(s)) for n, s in schema_dicts.items())


class Property(object):

    def __init__(self, schema, name=None, context=None):
        self.schema = Schema.from_legacy(schema)
        self.name = name
        self.context = context

    def required(self):
        return self.schema.required

    def implemented(self):
        return self.schema.implemented

    def update_allowed(self):
        return self.schema.update_allowed

    def immutable(self):
        return self.schema.immutable

    def has_default(self):
        return self.schema.default is not None

    def default(self):
        return self.schema.default

    def type(self):
        return self.schema.type

    def support_status(self):
        return self.schema.support_status

    def _get_integer(self, value):
        if value is None:
            value = self.has_default() and self.default() or 0
        try:
            value = int(value)
        except ValueError:
            raise TypeError(_("Value '%s' is not an integer") % value)
        else:
            return value

    def _get_number(self, value):
        if value is None:
            value = self.has_default() and self.default() or 0
        return Schema.str_to_num(value)

    def _get_string(self, value):
        if value is None:
            value = self.has_default() and self.default() or ''
        if not isinstance(value, six.string_types):
            if isinstance(value, (bool, int)):
                value = six.text_type(value)
            else:
                raise ValueError(_('Value must be a string'))
        return value

    def _get_children(self, child_values, keys=None, validate=False):
        if self.schema.schema is not None:
            if keys is None:
                keys = list(self.schema.schema)
            schemata = dict((k, self.schema.schema[k]) for k in keys)
            properties = Properties(schemata, dict(child_values),
                                    context=self.context)
            if validate:
                properties.validate()

            return ((k, properties[k]) for k in keys)
        else:
            return child_values

    def _get_map(self, value, validate=False):
        if value is None:
            value = self.default() if self.has_default() else {}
        if not isinstance(value, collections.Mapping):
            # This is to handle passing Lists via Json parameters exposed
            # via a provider resource, in particular lists-of-dicts which
            # cannot be handled correctly via comma_delimited_list
            if self.schema.allow_conversion:
                if isinstance(value, six.string_types):
                    return value
                elif isinstance(value, collections.Sequence):
                    return jsonutils.dumps(value)
            raise TypeError(_('"%s" is not a map') % value)

        return dict(self._get_children(six.iteritems(value),
                                       validate=validate))

    def _get_list(self, value, validate=False):
        if value is None:
            value = self.has_default() and self.default() or []
        if (not isinstance(value, collections.Sequence) or
                isinstance(value, six.string_types)):
            raise TypeError(_('"%s" is not a list') % repr(value))

        return [v[1] for v in self._get_children(enumerate(value),
                                                 range(len(value)),
                                                 validate)]

    def _get_bool(self, value):
        if value is None:
            value = self.has_default() and self.default() or False
        if isinstance(value, bool):
            return value
        normalised = value.lower()
        if normalised not in ['true', 'false']:
            raise ValueError(_('"%s" is not a valid boolean') % normalised)

        return normalised == 'true'

    def get_value(self, value, validate=False):
        """Get value from raw value and sanitize according to data type."""

        t = self.type()
        if t == Schema.STRING:
            _value = self._get_string(value)
        elif t == Schema.INTEGER:
            _value = self._get_integer(value)
        elif t == Schema.NUMBER:
            _value = self._get_number(value)
        elif t == Schema.MAP:
            _value = self._get_map(value, validate)
        elif t == Schema.LIST:
            _value = self._get_list(value, validate)
        elif t == Schema.BOOLEAN:
            _value = self._get_bool(value)

        if validate:
            self.schema.validate_constraints(_value, self.context)

        return _value


class Properties(collections.Mapping):

    def __init__(self, schema, data, resolver=lambda d: d, parent_name=None,
                 context=None, section=None):
        self.props = dict((k, Property(s, k, context))
                          for k, s in schema.items())
        self.resolve = resolver
        self.data = data
        self.error_prefix = []
        if parent_name is not None:
            self.error_prefix.append(parent_name)
        if section is not None:
            self.error_prefix.append(section)
        self.context = context

    @staticmethod
    def schema_from_params(params_snippet):
        """Convert a template snippet with parameters into a properties schema.

        :param params_snippet: parameter definition from a template
        :returns: an equivalent properties schema for the specified params
        """
        if params_snippet:
            return dict((n, Schema.from_parameter(p)) for n, p
                        in params_snippet.items())
        return {}

    def validate(self, with_value=True):
        try:
            for key in self.data:
                if key not in self.props:
                    msg = _("Unknown Property %s") % key
                    raise exception.StackValidationFailed(message=msg)

            for (key, prop) in self.props.items():
                # check that update_allowed and immutable
                # do not contradict each other
                if prop.update_allowed() and prop.immutable():
                    msg = _("Property %(prop)s: %(ua)s and %(im)s "
                            "cannot both be True") % {
                                'prop': key,
                                'ua': prop.schema.UPDATE_ALLOWED,
                                'im': prop.schema.IMMUTABLE}
                    raise exception.InvalidSchemaError(message=msg)

                if with_value:
                    try:
                        self._get_property_value(key, validate=True)
                    except exception.StackValidationFailed as ex:
                        path = [key]
                        path.extend(ex.path)
                        raise exception.StackValidationFailed(
                            path=path, message=ex.error_message)
                    except ValueError as e:
                        if prop.required() and key not in self.data:
                            path = []
                        else:
                            path = [key]
                        raise exception.StackValidationFailed(
                            path=path, message=six.text_type(e))

                # are there unimplemented Properties
                if not prop.implemented() and key in self.data:
                    msg = _("Property %s not implemented yet") % key
                    raise exception.StackValidationFailed(message=msg)
        except exception.StackValidationFailed as ex:
            # NOTE(prazumovsky): should reraise exception for adding specific
            # error name and error_prefix to path for correct error message
            # building.
            path = self.error_prefix
            path.extend(ex.path)
            raise exception.StackValidationFailed(
                error=ex.error or 'Property error',
                path=path,
                message=ex.error_message
            )

    def _find_deps_any_in_init(self, unresolved_value):
        deps = function.dependencies(unresolved_value)
        if any(res.action == res.INIT for res in deps):
            return True

    def get_user_value(self, key, validate=False):
        if key not in self:
            raise KeyError(_('Invalid Property %s') % key)

        prop = self.props[key]
        if key in self.data:
            try:
                unresolved_value = self.data[key]
                if validate:
                    if self._find_deps_any_in_init(unresolved_value):
                        validate = False

                value = self.resolve(unresolved_value)
                return prop.get_value(value, validate)
            # Children can raise StackValidationFailed with unique path which
            # is necessary for further use in StackValidationFailed exception.
            # So we need to handle this exception in this method.
            except exception.StackValidationFailed as e:
                raise exception.StackValidationFailed(path=e.path,
                                                      message=e.error_message)
            # the resolver function could raise any number of exceptions,
            # so handle this generically
            except Exception as e:
                raise ValueError(six.text_type(e))

    def _get_property_value(self, key, validate=False):
        if key not in self:
            raise KeyError(_('Invalid Property %s') % key)

        prop = self.props[key]
        if key in self.data:
            return self.get_user_value(key, validate)
        elif prop.has_default():
            return prop.get_value(None, validate)
        elif prop.required():
            raise ValueError(_('Property %s not assigned') % key)

    def __getitem__(self, key):
        return self._get_property_value(key)

    def __len__(self):
        return len(self.props)

    def __contains__(self, key):
        return key in self.props

    def __iter__(self):
        return iter(self.props)

    @staticmethod
    def _param_def_from_prop(schema):
        """Return a template parameter definition corresponding to property."""
        param_type_map = {
            schema.INTEGER: parameters.Schema.NUMBER,
            schema.STRING: parameters.Schema.STRING,
            schema.NUMBER: parameters.Schema.NUMBER,
            schema.BOOLEAN: parameters.Schema.BOOLEAN,
            schema.MAP: parameters.Schema.MAP,
            schema.LIST: parameters.Schema.LIST,
        }

        def param_items():
            yield parameters.TYPE, param_type_map[schema.type]

            if schema.description is not None:
                yield parameters.DESCRIPTION, schema.description

            if schema.default is not None:
                yield parameters.DEFAULT, schema.default

            for constraint in schema.constraints:
                if isinstance(constraint, constr.Length):
                    if constraint.min is not None:
                        yield parameters.MIN_LENGTH, constraint.min
                    if constraint.max is not None:
                        yield parameters.MAX_LENGTH, constraint.max
                elif isinstance(constraint, constr.Range):
                    if constraint.min is not None:
                        yield parameters.MIN_VALUE, constraint.min
                    if constraint.max is not None:
                        yield parameters.MAX_VALUE, constraint.max
                elif isinstance(constraint, constr.AllowedValues):
                    yield parameters.ALLOWED_VALUES, list(constraint.allowed)
                elif isinstance(constraint, constr.AllowedPattern):
                    yield parameters.ALLOWED_PATTERN, constraint.pattern

            if schema.type == schema.BOOLEAN:
                yield parameters.ALLOWED_VALUES, ['True', 'true',
                                                  'False', 'false']

        return dict(param_items())

    @staticmethod
    def _prop_def_from_prop(name, schema):
        """Return a provider template property definition for a property."""
        if schema.type == Schema.LIST:
            return {'Fn::Split': [',', {'Ref': name}]}
        else:
            return {'Ref': name}

    @staticmethod
    def _hot_param_def_from_prop(schema):
        """Parameter definition corresponding to property for hot template."""
        param_type_map = {
            schema.INTEGER: hot_param.HOTParamSchema.NUMBER,
            schema.STRING: hot_param.HOTParamSchema.STRING,
            schema.NUMBER: hot_param.HOTParamSchema.NUMBER,
            schema.BOOLEAN: hot_param.HOTParamSchema.BOOLEAN,
            schema.MAP: hot_param.HOTParamSchema.MAP,
            schema.LIST: hot_param.HOTParamSchema.LIST,
        }

        def param_items():
            yield hot_param.HOTParamSchema.TYPE, param_type_map[schema.type]

            if schema.description is not None:
                yield hot_param.HOTParamSchema.DESCRIPTION, schema.description

            if schema.default is not None:
                yield hot_param.HOTParamSchema.DEFAULT, schema.default

            for constraint in schema.constraints:
                if (isinstance(constraint, constr.Length) or
                        isinstance(constraint, constr.Range)):
                    if constraint.min is not None:
                        yield hot_param.MIN, constraint.min
                    if constraint.max is not None:
                        yield hot_param.MAX, constraint.max
                elif isinstance(constraint, constr.AllowedValues):
                    yield hot_param.ALLOWED_VALUES, list(constraint.allowed)
                elif isinstance(constraint, constr.AllowedPattern):
                    yield hot_param.ALLOWED_PATTERN, constraint.pattern

            if schema.type == schema.BOOLEAN:
                yield hot_param.ALLOWED_VALUES, ['True', 'true',
                                                 'False', 'false']

        return dict(param_items())

    @staticmethod
    def _hot_prop_def_from_prop(name, schema):
        """Return a provider template property definition for a property."""
        return {'get_param': name}

    @classmethod
    def schema_to_parameters_and_properties(cls, schema, template_type='cfn'):
        """Generates properties with params resolved for a schema.

        :param schema: A resource type's properties_schema
        :returns: A tuple of params and properties dicts

        ex: input:  {'foo': {'Type': 'List'}}
            output: {'foo': {'Type': 'CommaDelimitedList'}},
                    {'foo': {'Fn::Split': {'Ref': 'foo'}}}

        ex: input:  {'foo': {'Type': 'String'}, 'bar': {'Type': 'Map'}}
            output: {'foo': {'Type': 'String'}, 'bar': {'Type': 'Json'}},
                    {'foo': {'Ref': 'foo'}, 'bar': {'Ref': 'bar'}}
        """
        def param_prop_def_items(name, schema, template_type):
            if template_type == 'hot':
                param_def = cls._hot_param_def_from_prop(schema)
                prop_def = cls._hot_prop_def_from_prop(name, schema)
            else:
                param_def = cls._param_def_from_prop(schema)
                prop_def = cls._prop_def_from_prop(name, schema)
            return (name, param_def), (name, prop_def)

        if not schema:
            return {}, {}

        param_prop_defs = [param_prop_def_items(n, s, template_type)
                           for n, s in six.iteritems(schemata(schema))
                           if s.implemented]
        param_items, prop_items = zip(*param_prop_defs)
        return dict(param_items), dict(prop_items)


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
        elif not isinstance(self.properties, Properties):
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
                props = dict((k, Property(s, k))
                             for k, s in schemata.items())
            return props

        source_key = path[0]
        data = self.properties.data
        props = self.properties.props
        for key in path:
            if isinstance(data, list):
                source_key = key
            elif data.get(key) is not None and isinstance(data.get(key),
                                                          (list, dict)):
                data = data.get(key)
                props = get_props(props, key)
            elif data.get(key) is None:
                if (self.rule == TranslationRule.DELETE or
                        (self.rule == TranslationRule.REPLACE and
                         self.value_name)):
                    return None, None
                elif props.get(key).type() == Schema.LIST:
                    data[key] = []
                elif props.get(key).type() == Schema.MAP:
                    data[key] = {}
                else:
                    source_key = key
                    continue
                data = data.get(key)
                props = get_props(props, key)
            else:
                source_key = key
        return source_key, data
