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

from oslo_utils import strutils
import six

from heat.common.i18n import _
from heat.common.i18n import repr_wrapper
from heat.engine import constraints as constr
from heat.engine import support

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class Schema(constr.Schema):
    """Simple schema class for attributes.

    Schema objects are serializable to dictionaries following a superset of
    the HOT input Parameter schema using dict().
    """

    KEYS = (
        DESCRIPTION, TYPE
    ) = (
        'description', 'type',
    )

    CACHE_MODES = (
        CACHE_LOCAL,
        CACHE_NONE
    ) = (
        'cache_local',
        'cache_none'
    )

    TYPES = (
        STRING, MAP, LIST, INTEGER, BOOLEAN
    ) = (
        'String', 'Map', 'List', 'Integer', 'Boolean'
    )

    def __init__(self, description=None,
                 support_status=support.SupportStatus(),
                 cache_mode=CACHE_LOCAL,
                 type=None):
        self.description = description
        self.support_status = support_status
        self.cache_mode = cache_mode
        self.type = type

    def __getitem__(self, key):
        if key == self.DESCRIPTION:
            if self.description is not None:
                return self.description

        elif key == self.TYPE:
            if self.type is not None:
                return self.type.lower()

        raise KeyError(key)

    @classmethod
    def from_attribute(cls, schema_dict):
        """Return a Property Schema corresponding to a Attribute Schema."""
        msg = 'Old attribute schema is not supported'
        assert isinstance(schema_dict, cls), msg
        return schema_dict


def schemata(schema):
    """Return dictionary of Schema objects for given dictionary of schemata."""
    return dict((n, Schema.from_attribute(s)) for n, s in schema.items())


class Attribute(object):
    """An Attribute schema."""

    def __init__(self, attr_name, schema):
        """Initialise with a name and schema.

        :param attr_name: the name of the attribute
        :param schema: attribute schema
        """
        self.name = attr_name
        self.schema = Schema.from_attribute(schema)

    def support_status(self):
        return self.schema.support_status

    def as_output(self, resource_name, template_type='cfn'):
        """Output entry for a provider template with the given resource name.

        :param resource_name: the logical name of the provider resource
        :param template_type: the template type to generate
        :returns: This attribute as a template 'Output' entry for
                  cfn template and 'output' entry for hot template
        """
        if template_type == 'hot':
            return {
                "value": {"get_attr": [resource_name, self.name]},
                "description": self.schema.description
            }
        else:
            return {
                "Value": {"Fn::GetAtt": [resource_name, self.name]},
                "Description": self.schema.description
            }


def _stack_id_output(resource_name, template_type='cfn'):
    if template_type == 'hot':
        return {
            "value": {"get_resource": resource_name},
        }
    else:
        return {
            "Value": {"Ref": resource_name},
        }


BASE_ATTRIBUTES = (SHOW_ATTR, ) = ('show', )

# Returned by function.dep_attrs() to indicate that all attributes are
# referenced
ALL_ATTRIBUTES = '*'


@repr_wrapper
class Attributes(collections.Mapping):
    """Models a collection of Resource Attributes."""

    def __init__(self, res_name, schema, resolver):
        self._resource_name = res_name
        self._resolver = resolver
        self.set_schema(schema)
        self.reset_resolved_values()

        assert ALL_ATTRIBUTES not in schema, \
            "Invalid attribute name '%s'" % ALL_ATTRIBUTES

    def reset_resolved_values(self):
        if hasattr(self, '_resolved_values'):
            self._has_new_resolved = len(self._resolved_values) > 0
        else:
            self._has_new_resolved = False
        self._resolved_values = {}

    def set_schema(self, schema):
        self._attributes = self._make_attributes(schema)

    def get_cache_mode(self, attribute_name):
        """Return the cache mode for the specified attribute.

        If the attribute is not defined in the schema, the default cache
        mode (CACHE_LOCAL) is returned.
        """
        try:
            return self._attributes[attribute_name].schema.cache_mode
        except KeyError:
            return Schema.CACHE_LOCAL

    @staticmethod
    def _make_attributes(schema):
        return dict((n, Attribute(n, d)) for n, d in schema.items())

    @staticmethod
    def as_outputs(resource_name, resource_class, template_type='cfn'):
        """Dict of Output entries for a provider template with resource name.

        :param resource_name: logical name of the resource
        :param resource_class: resource implementation class
        :returns: The attributes of the specified resource_class as a template
                  Output map
        """
        attr_schema = {}
        for name, schema_data in resource_class.attributes_schema.items():
            schema = Schema.from_attribute(schema_data)
            if schema.support_status.status != support.HIDDEN:
                attr_schema[name] = schema
        attr_schema.update(resource_class.base_attributes_schema)
        attribs = Attributes._make_attributes(attr_schema).items()

        outp = dict((n, att.as_output(resource_name,
                                      template_type)) for n, att in attribs)
        outp['OS::stack_id'] = _stack_id_output(resource_name, template_type)
        return outp

    @staticmethod
    def schema_from_outputs(json_snippet):
        if json_snippet:
            return dict((k, Schema(v.get("Description")))
                        for k, v in json_snippet.items())
        return {}

    def _validate_type(self, attrib, value):
        if attrib.schema.type == attrib.schema.STRING:
            if not isinstance(value, six.string_types):
                LOG.warning("Attribute %(name)s is not of type "
                            "%(att_type)s",
                            {'name': attrib.name,
                             'att_type': attrib.schema.STRING})
        elif attrib.schema.type == attrib.schema.LIST:
            if (not isinstance(value, collections.Sequence)
                    or isinstance(value, six.string_types)):
                LOG.warning("Attribute %(name)s is not of type "
                            "%(att_type)s",
                            {'name': attrib.name,
                             'att_type': attrib.schema.LIST})
        elif attrib.schema.type == attrib.schema.MAP:
            if not isinstance(value, collections.Mapping):
                LOG.warning("Attribute %(name)s is not of type "
                            "%(att_type)s",
                            {'name': attrib.name,
                             'att_type': attrib.schema.MAP})
        elif attrib.schema.type == attrib.schema.INTEGER:
            if not isinstance(value, int):
                LOG.warning("Attribute %(name)s is not of type "
                            "%(att_type)s",
                            {'name': attrib.name,
                             'att_type': attrib.schema.INTEGER})
        elif attrib.schema.type == attrib.schema.BOOLEAN:
            try:
                strutils.bool_from_string(value, strict=True)
            except ValueError:
                LOG.warning("Attribute %(name)s is not of type "
                            "%(att_type)s",
                            {'name': attrib.name,
                             'att_type': attrib.schema.BOOLEAN})

    @property
    def cached_attrs(self):
        return self._resolved_values

    @cached_attrs.setter
    def cached_attrs(self, c_attrs):
        if c_attrs is None:
            self._resolved_values = {}
        else:
            self._resolved_values = c_attrs
        self._has_new_resolved = False

    def set_cached_attr(self, key, value):
        self._resolved_values[key] = value
        self._has_new_resolved = True

    def has_new_cached_attrs(self):
        """Returns True if cached_attrs have changed

        Allows the caller to determine if this instance's cached_attrs
        have been updated since they were initially set (if at all).
        """
        return self._has_new_resolved

    def __getitem__(self, key):
        if key not in self:
            raise KeyError(_('%(resource)s: Invalid attribute %(key)s') %
                           dict(resource=self._resource_name, key=key))

        attrib = self._attributes.get(key)
        if attrib.schema.cache_mode == Schema.CACHE_NONE:
            return self._resolver(key)

        if key in self._resolved_values:
            return self._resolved_values[key]

        value = self._resolver(key)

        if value is not None:
            # validate the value against its type
            self._validate_type(attrib, value)
            # only store if not None, it may resolve to an actual value
            # on subsequent calls
            self.set_cached_attr(key, value)
        return value

    def __len__(self):
        return len(self._attributes)

    def __contains__(self, key):
        return key in self._attributes

    def __iter__(self):
        return iter(self._attributes)

    def __repr__(self):
        return ("Attributes for %s:\n\t" % self._resource_name +
                '\n\t'.join(six.itervalues(self)))


def select_from_attribute(attribute_value, path):
    """Select an element from an attribute value.

    :param attribute_value: the attribute value.
    :param path: a list of path components to select from the attribute.
    :returns: the selected attribute component value.
    """
    def get_path_component(collection, key):
        if not isinstance(collection, (collections.Mapping,
                                       collections.Sequence)):
            raise TypeError(_("Can't traverse attribute path"))

        if not isinstance(key, (six.string_types, int)):
            raise TypeError(_('Path components in attributes must be strings'))

        return collection[key]

    try:
        return six.moves.reduce(get_path_component, path, attribute_value)
    except (KeyError, IndexError, TypeError):
        return None
