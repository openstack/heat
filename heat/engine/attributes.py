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
    An attribute description and resolved value.

    :param resource_name: the logical name of the resource having this
                          attribute
    :param attr_name: the name of the attribute
    :param description: attribute description
    :param resolver: a function that will resolve the value of this attribute
    """

    def __init__(self, attr_name, description, resolver):
        self._name = attr_name
        self._description = description
        self._resolve = resolver

    @property
    def name(self):
        """
        :returns: The attribute name
        """
        return self._name

    @property
    def value(self):
        """
        :returns: The resolved attribute value
        """
        return self._resolve(self._name)

    @property
    def description(self):
        """
        :returns: A description of the attribute
        """
        return self._description

    @staticmethod
    def as_output(resource_name, attr_name, description):
        """
        :param resource_name: the logical name of a resource
        :param attr_name: the name of the attribute
        :description: the description of the attribute
        :returns: This attribute as a template 'Output' entry
        """
        return {
            attr_name: {
                "Value": '{"Fn::GetAtt": ["%s", "%s"]}' % (resource_name,
                                                           attr_name),
                "Description": description
            }
        }

    def __call__(self):
        return self.value

    def __str__(self):
        return ("Attribute %s: %s" % (self.name, self.value))


class Attributes(collections.Mapping):
    """Models a collection of Resource Attributes."""

    def __init__(self, res_name, schema, resolver):
        self._resource_name = res_name
        self._attributes = dict((k, Attribute(k, v, resolver))
                                for k, v in schema.items())

    @property
    def attributes(self):
        """
        Get a copy of the attribute definitions in this collection
        (as opposed to attribute values); useful for doc and
        template format generation

        :returns: attribute definitions
        """
        # return a deep copy to avoid modification
        return dict((k, Attribute(k, v.description, v._resolve)) for k, v
                    in self._attributes.items())

    @staticmethod
    def as_outputs(resource_name, resource_class):
        """
        :param resource_name: logical name of the resource
        :param resource_class: resource implementation class
        :returns: The attributes of the specified resource_class as a template
                  Output map
        """
        outputs = {}
        for name, descr in resource_class.attributes_schema.items():
            outputs.update(Attribute.as_output(resource_name, name, descr))
        return outputs

    @staticmethod
    def schema_from_outputs(json_snippet):
        return dict(("Outputs.%s" % k, v.get("Description"))
                    for k, v in json_snippet.items())

    def __getitem__(self, key):
        if key not in self:
            raise KeyError('%s: Invalid attribute %s' %
                           (self._resource_name, key))
        return self._attributes[key]()

    def __len__(self):
        return len(self._attributes)

    def __contains__(self, key):
        return key in self._attributes

    def __iter__(self):
        return iter(self._attributes)

    def __repr__(self):
        return ("Attributes for %s:\n\t" % self._resource_name +
                '\n\t'.join(self._attributes.values()))
