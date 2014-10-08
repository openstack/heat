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
from heat.engine import constraints as constr
from heat.engine import function
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
    """
    Schema class for validating resource properties.

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
                 support_status=support.SupportStatus()):
        super(Schema, self).__init__(data_type, description, default,
                                     schema, required, constraints)
        self.implemented = implemented
        self.update_allowed = update_allowed
        self.immutable = immutable
        self.support_status = support_status
        # validate structural correctness of schema itself
        self.validate()

    @classmethod
    def from_legacy(cls, schema_dict):
        """
        Return a Property Schema object from a legacy schema dictionary.
        """

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
        """
        Return a Property Schema corresponding to a Parameter Schema.

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

        # make update_allowed true by default on TemplateResources
        # as the template should deal with this.
        return cls(data_type=param_type_map.get(param.type, cls.MAP),
                   description=param.description,
                   required=param.required,
                   constraints=param.constraints,
                   update_allowed=True,
                   immutable=False)

    def allowed_param_prop_type(self):
        """
        Return allowed type of Property Schema converted from parameter.

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

        raise KeyError(key)


def schemata(schema_dicts):
    """
    Return dictionary of Schema objects for given dictionary of schemata.

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
        if not isinstance(value, basestring):
            raise ValueError(_('Value must be a string'))
        return value

    def _get_children(self, child_values, keys=None, validate=False):
        if self.schema.schema is not None:
            if keys is None:
                keys = list(self.schema.schema)
            schemata = dict((k, self.schema.schema[k]) for k in keys)
            properties = Properties(schemata, dict(child_values),
                                    parent_name=self.name,
                                    context=self.context)
            if validate:
                properties.validate()

            return ((k, properties[k]) for k in keys)
        else:
            return child_values

    def _get_map(self, value, validate=False):
        if value is None:
            value = self.has_default() and self.default() or {}
        if not isinstance(value, collections.Mapping):
            raise TypeError(_('"%s" is not a map') % value)

        return dict(self._get_children(six.iteritems(value),
                                       validate=validate))

    def _get_list(self, value, validate=False):
        if value is None:
            value = self.has_default() and self.default() or []
        if (not isinstance(value, collections.Sequence) or
                isinstance(value, basestring)):
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

        # property value resolves to None if resource it depends on is not
        # created. So, if value is None skip constraint validation.
        if value is not None and validate:
            self.schema.validate_constraints(_value, self.context)

        return _value


class Properties(collections.Mapping):

    def __init__(self, schema, data, resolver=lambda d: d, parent_name=None,
                 context=None):
        self.props = dict((k, Property(s, k, context))
                          for k, s in schema.items())
        self.resolve = resolver
        self.data = data
        if parent_name is None:
            self.error_prefix = ''
        else:
            self.error_prefix = '%s: ' % parent_name
        self.context = context

    @staticmethod
    def schema_from_params(params_snippet):
        """
        Convert a template snippet that defines parameters
        into a properties schema

        :param params_snippet: parameter definition from a template
        :returns: an equivalent properties schema for the specified params
        """
        if params_snippet:
            return dict((n, Schema.from_parameter(p)) for n, p
                        in params_snippet.items())
        return {}

    def validate(self, with_value=True):
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
                except ValueError as e:
                    msg = _("Property error : %s") % e
                    raise exception.StackValidationFailed(message=msg)

            # are there unimplemented Properties
            if not prop.implemented() and key in self.data:
                msg = _("Property %s not implemented yet") % key
                raise exception.StackValidationFailed(message=msg)

        for key in self.data:
            if key not in self.props:
                msg = _("Unknown Property %s") % key
                raise exception.StackValidationFailed(message=msg)

    def _get_property_value(self, key, validate=False):
        if key not in self:
            raise KeyError(_('%(prefix)sInvalid Property %(key)s') %
                           {'prefix': self.error_prefix, 'key': key})

        prop = self.props[key]

        if key in self.data:
            try:
                unresolved_value = self.data[key]
                if validate:
                    deps = function.dependencies(unresolved_value)
                    if any(res.action == res.INIT for res in deps):
                        validate = False

                value = self.resolve(unresolved_value)
                return prop.get_value(value, validate)
            # the resolver function could raise any number of exceptions,
            # so handle this generically
            except Exception as e:
                raise ValueError('%s%s %s' % (self.error_prefix, key,
                                              six.text_type(e)))
        elif prop.has_default():
            return prop.get_value(None, validate)
        elif prop.required():
            raise ValueError(_('%(prefix)sProperty %(key)s not assigned') %
                             {'prefix': self.error_prefix, 'key': key})

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
        """
        Return a template parameter definition corresponding to a property.
        """
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
        """
        Return a provider template property definition for a property.
        """
        if schema.type == Schema.LIST:
            return {'Fn::Split': [',', {'Ref': name}]}
        else:
            return {'Ref': name}

    @classmethod
    def schema_to_parameters_and_properties(cls, schema):
        """Generates properties with params resolved for a resource's
        properties_schema.

        :param schema: A resource type's properties_schema
        :returns: A tuple of params and properties dicts

        ex: input:  {'foo': {'Type': 'String'}}
            output: {'foo': {'Type': 'String'}},
                    {'foo': {'Ref': 'foo'}}

        ex: input:  {'foo': {'Type': 'List'}, 'bar': {'Type': 'Map'}}
            output: {'foo': {'Type': 'CommaDelimitedList'}
                     'bar': {'Type': 'Json'}},
                    {'foo': {'Fn::Split': {'Ref': 'foo'}},
                     'bar': {'Ref': 'bar'}}

        """
        def param_prop_def_items(name, schema):
            param_def = cls._param_def_from_prop(schema)
            prop_def = cls._prop_def_from_prop(name, schema)

            return (name, param_def), (name, prop_def)

        if not schema:
            return {}, {}

        param_prop_defs = [param_prop_def_items(n, s)
                           for n, s in six.iteritems(schemata(schema))
                           if s.implemented]
        param_items, prop_items = zip(*param_prop_defs)
        return dict(param_items), dict(prop_items)
