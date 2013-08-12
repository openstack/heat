# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


class Attribute(object):
    """
    An Attribute schema.
    """

    (DESCRIPTION,) = ('description',)

    def __init__(self, attr_name, description):
        """
        Initialise with a name and description.

        :param attr_name: the name of the attribute
        :param description: attribute description
        """
        self.name = attr_name
        self.description = description

    def as_output(self, resource_name):
        """
        Return an Output schema entry for a provider template with the given
        resource name.

        :param resource_name: the logical name of the provider resource
        :returns: This attribute as a template 'Output' entry
        """
        return {
            "Value": '{"Fn::GetAtt": ["%s", "%s"]}' % (resource_name,
                                                       self.name),
            "Description": self.description
        }


class Attributes(collections.Mapping):
    """Models a collection of Resource Attributes."""

    def __init__(self, res_name, schema, resolver):
        self._resource_name = res_name
        self._resolver = resolver
        self._attributes = Attributes._make_attributes(schema)

    @staticmethod
    def _make_attributes(schema):
        return dict((n, Attribute(n, d)) for n, d in schema.items())

    @staticmethod
    def as_outputs(resource_name, resource_class):
        """
        :param resource_name: logical name of the resource
        :param resource_class: resource implementation class
        :returns: The attributes of the specified resource_class as a template
                  Output map
        """
        schema = resource_class.attributes_schema
        attribs = Attributes._make_attributes(schema).items()

        return dict((n, att.as_output(resource_name)) for n, att in attribs)

    @staticmethod
    def schema_from_outputs(json_snippet):
        if json_snippet:
            return dict((k, v.get("Description"))
                        for k, v in json_snippet.items())
        return {}

    def __getitem__(self, key):
        if key not in self:
            raise KeyError('%s: Invalid attribute %s' %
                           (self._resource_name, key))
        return self._resolver(key)

    def __len__(self):
        return len(self._attributes)

    def __contains__(self, key):
        return key in self._attributes

    def __iter__(self):
        return iter(self._attributes)

    def __repr__(self):
        return ("Attributes for %s:\n\t" % self._resource_name +
                '\n\t'.join(self._attributes.values()))
