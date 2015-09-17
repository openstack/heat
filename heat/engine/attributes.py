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
from heat.common.i18n import _LW
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
                "value": '{"get_attr": ["%s", "%s"]}' % (resource_name,
                                                         self.name),
                "description": self.schema.description
            }
        else:
            return {
                "Value": '{"Fn::GetAtt": ["%s", "%s"]}' % (resource_name,
                                                           self.name),
                "Description": self.schema.description
            }


class Attributes(collections.Mapping):
    """Models a collection of Resource Attributes."""

    def __init__(self, res_name, schema, resolver):
        self._resource_name = res_name
        self._resolver = resolver
        self._attributes = Attributes._make_attributes(schema)
        self.reset_resolved_values()

    def reset_resolved_values(self):
        self._resolved_values = {}

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
        schema = resource_class.attributes_schema.copy()
        schema.update(resource_class.base_attributes_schema)
        attribs = Attributes._make_attributes(schema).items()

        return dict((n, att.as_output(resource_name,
                                      template_type)) for n, att in attribs)

    @staticmethod
    def schema_from_outputs(json_snippet):
        if json_snippet:
            return dict((k, Schema(v.get("Description")))
                        for k, v in json_snippet.items())
        return {}

    def _validate_type(self, attrib, value):
        if attrib.schema.type == attrib.schema.STRING:
            if not isinstance(value, six.string_types):
                LOG.warn(_LW("Attribute %(name)s is not of type %(att_type)s"),
                         {'name': attrib.name,
                          'att_type': attrib.schema.STRING})
        elif attrib.schema.type == attrib.schema.LIST:
            if (not isinstance(value, collections.Sequence)
                    or isinstance(value, six.string_types)):
                LOG.warn(_LW("Attribute %(name)s is not of type %(att_type)s"),
                         {'name': attrib.name,
                          'att_type': attrib.schema.LIST})
        elif attrib.schema.type == attrib.schema.MAP:
            if not isinstance(value, collections.Mapping):
                LOG.warn(_LW("Attribute %(name)s is not of type %(att_type)s"),
                         {'name': attrib.name,
                          'att_type': attrib.schema.MAP})
        elif attrib.schema.type == attrib.schema.INTEGER:
            if not isinstance(value, int):
                LOG.warn(_LW("Attribute %(name)s is not of type %(att_type)s"),
                         {'name': attrib.name,
                          'att_type': attrib.schema.INTEGER})
        elif attrib.schema.type == attrib.schema.BOOLEAN:
            try:
                strutils.bool_from_string(value, strict=True)
            except ValueError:
                LOG.warn(_LW("Attribute %(name)s is not of type %(att_type)s"),
                         {'name': attrib.name,
                          'att_type': attrib.schema.BOOLEAN})

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
            self._resolved_values[key] = value
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


class DynamicSchemeAttributes(Attributes):
    """The collection of attributes for resources without static attr scheme.

    The class defines collection of attributes for such entities as Resource
    Group, Software Deployment and so on that doesn't have static attribute
    scheme. The attribute scheme for such kind of resources can contain
    attribute from attribute scheme (like other resources) and dynamic
    attributes (nested stack attrs or API response attrs).
    """

    def __getitem__(self, key):
        try:
            # check if the value can be resolved with attributes
            # in attributes schema (static attributes)
            return super(DynamicSchemeAttributes, self).__getitem__(key)
        except KeyError:
            # ok, the attribute is not present in attribute scheme
            # try to check the attributes dynamically
            if key in self._resolved_values:
                return self._resolved_values[key]

            value = self._resolver(key)
            if value is not None:
                self._resolved_values[key] = value

            return value


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
