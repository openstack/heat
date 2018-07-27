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
from heat.common import param_utils
from heat.engine import constraints as constr
from heat.engine import function
from heat.engine.hot import parameters as hot_param
from heat.engine import parameters
from heat.engine import support
from heat.engine import translation as trans

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
                                     schema, required, constraints,
                                     immutable=immutable)
        self.implemented = implemented
        self.update_allowed = update_allowed
        self.support_status = support_status
        self.allow_conversion = allow_conversion
        # validate structural correctness of schema itself
        self.validate()

    def validate(self, context=None):
        super(Schema, self).validate()
        # check that update_allowed and immutable
        # do not contradict each other
        if self.update_allowed and self.immutable:
            msg = _("Options %(ua)s and %(im)s "
                    "cannot both be True") % {
                        'ua': UPDATE_ALLOWED,
                        'im': IMMUTABLE}
            raise exception.InvalidSchemaError(message=msg)

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
        allow_conversion = (param.type == param.MAP
                            or param.type == param.LIST)

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(data_type=param_type_map.get(param.type, cls.MAP),
                   description=param.description,
                   required=param.required,
                   constraints=param.constraints,
                   update_allowed=True,
                   immutable=False,
                   allow_conversion=allow_conversion)

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

    def __init__(self, schema, name=None, context=None, path=None):
        self.schema = Schema.from_legacy(schema)
        self.name = name
        self.context = context
        self.path = self.make_path(name, path)

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

    def make_path(self, name, path=None):
        if path is None:
            path = ''
        if name is None:
            name = ''

        if isinstance(name, int) or name.isdigit():
            name = str(name)

        delim = '' if not path or path.endswith('.') else '.'
        return delim.join([path, name])

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
                raise ValueError(_('Value must be a string; got %r') % value)
        return value

    def _get_children(self, child_values, keys=None, validate=False,
                      translation=None):
        if self.schema.schema is not None:
            if keys is None:
                keys = list(self.schema.schema)
            schemata = dict((k, self.schema.schema[k]) for k in keys)
            properties = Properties(schemata, dict(child_values),
                                    context=self.context,
                                    parent_name=self.path,
                                    translation=translation)
            if validate:
                properties.validate()

            return ((k, properties[k]) for k in keys)
        else:
            return child_values

    def _get_map(self, value, validate=False, translation=None):
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
                                       validate=validate,
                                       translation=translation))

    def _get_list(self, value, validate=False, translation=None):
        if value is None:
            value = self.has_default() and self.default() or []
        if self.schema.allow_conversion and isinstance(value,
                                                       six.string_types):
                value = param_utils.delim_string_to_list(value)
        if (not isinstance(value, collections.Sequence) or
                isinstance(value, six.string_types)):
            raise TypeError(_('"%s" is not a list') % repr(value))

        return [v[1] for v in self._get_children(enumerate(value),
                                                 range(len(value)),
                                                 validate=validate,
                                                 translation=translation)]

    def _get_bool(self, value):
        """Get value for boolean property.

        Explicitly checking for bool, or string with lower value
        "true" or "false", to avoid integer values.
        """
        if value is None:
            value = self.has_default() and self.default() or False
        if isinstance(value, bool):
            return value
        if isinstance(value, six.string_types):
            normalised = value.lower()
            if normalised not in ['true', 'false']:
                raise ValueError(_('"%s" is not a valid boolean') % normalised)
            return normalised == 'true'

        raise TypeError(_('"%s" is not a valid boolean') % value)

    def get_value(self, value, validate=False, translation=None):
        """Get value from raw value and sanitize according to data type."""

        t = self.type()
        if t == Schema.STRING:
            _value = self._get_string(value)
        elif t == Schema.INTEGER:
            _value = self._get_integer(value)
        elif t == Schema.NUMBER:
            _value = self._get_number(value)
        elif t == Schema.MAP:
            _value = self._get_map(value, validate, translation)
        elif t == Schema.LIST:
            _value = self._get_list(value, validate, translation)
        elif t == Schema.BOOLEAN:
            _value = self._get_bool(value)
        elif t == Schema.ANY:
            _value = value

        if validate:
            self.schema.validate_constraints(_value, self.context)

        return _value


class Properties(collections.Mapping):

    def __init__(self, schema, data, resolver=lambda d: d, parent_name=None,
                 context=None, section=None, translation=None):
        self.props = dict((k, Property(s, k, context, path=parent_name))
                          for k, s in schema.items())
        self.resolve = resolver
        self.data = data
        self.error_prefix = [section] if section is not None else []
        self.parent_name = parent_name
        self.context = context
        self.translation = (trans.Translation(properties=self)
                            if translation is None else translation)

    def update_translation(self, rules, client_resolve=True,
                           ignore_resolve_error=False):
        self.translation.set_rules(rules, client_resolve=client_resolve,
                                   ignore_resolve_error=ignore_resolve_error)

    @staticmethod
    def schema_from_params(params_snippet):
        """Create properties schema from the parameters section of a template.

        :param params_snippet: parameter definition from a template
        :returns: equivalent properties schemata for the specified parameters
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
                if (self.translation.is_deleted(prop.path) or
                        self.translation.is_replaced(prop.path)):
                    continue
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
        if (self.translation.is_deleted(prop.path) or
                self.translation.is_replaced(prop.path)):
            return
        if key in self.data:
            try:
                unresolved_value = self.data[key]
                if validate:
                    if self._find_deps_any_in_init(unresolved_value):
                        validate = False

                value = self.resolve(unresolved_value)

                if self.translation.has_translation(prop.path):
                    value = self.translation.translate(prop.path,
                                                       value,
                                                       self.data)

                return prop.get_value(value, validate,
                                      translation=self.translation)
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
        if not self.translation.is_deleted(prop.path) and key in self.data:
            return self.get_user_value(key, validate)
        elif self.translation.has_translation(prop.path):
            value = self.translation.translate(prop.path, prop_data=self.data,
                                               validate=validate)
            if value is not None or prop.has_default():
                return prop.get_value(value)
            elif prop.required():
                raise ValueError(_('Property %s not assigned') % key)
        elif prop.has_default():
            return prop.get_value(None, validate,
                                  translation=self.translation)
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

            def constraint_items(constraint):

                def range_min_max(constraint):
                    if constraint.min is not None:
                        yield hot_param.MIN, constraint.min
                    if constraint.max is not None:
                        yield hot_param.MAX, constraint.max

                if isinstance(constraint, constr.Length):
                    yield hot_param.LENGTH, dict(range_min_max(constraint))
                elif isinstance(constraint, constr.Range):
                    yield hot_param.RANGE, dict(range_min_max(constraint))
                elif isinstance(constraint, constr.AllowedValues):
                    yield hot_param.ALLOWED_VALUES, list(constraint.allowed)
                elif isinstance(constraint, constr.AllowedPattern):
                    yield hot_param.ALLOWED_PATTERN, constraint.pattern

            if schema.constraints:
                yield (hot_param.HOTParamSchema.CONSTRAINTS,
                       [dict(constraint_items(constraint)) for constraint
                        in schema.constraints])

        return dict(param_items())

    @staticmethod
    def _hot_prop_def_from_prop(name, schema):
        """Return a provider template property definition for a property."""
        return {'get_param': name}

    @classmethod
    def schema_to_parameters_and_properties(cls, schema, template_type='cfn'):
        """Convert a schema to template parameters and properties.

        This can be used to generate a provider template that matches the
        given properties schemata.

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
