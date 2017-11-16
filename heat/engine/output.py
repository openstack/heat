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
import copy
import six

from heat.common import exception
from heat.engine import function


# Field names that can be passed to Template.get_section_name() in order to
# determine the appropriate name for a particular template format.
FIELDS = (
    VALUE, DESCRIPTION,
) = (
    'Value', 'Description',
)


class OutputDefinition(object):
    """A definition of a stack output, independent of any template format."""

    def __init__(self, name, value, description=None):
        self.name = name
        self._value = value
        self._resolved_value = None
        self._description = description
        self._deps = None
        self._all_dep_attrs = None

    def validate(self):
        """Validate the output value without resolving it."""
        function.validate(self._value, VALUE)

    def required_resource_names(self):
        if self._deps is None:
            try:
                required_resources = function.dependencies(self._value)
                self._deps = set(six.moves.map(lambda rp: rp.name,
                                               required_resources))
            except (exception.InvalidTemplateAttribute,
                    exception.InvalidTemplateReference):
                # This output ain't gonna work anyway
                self._deps = set()
        return self._deps

    def dep_attrs(self, resource_name, load_all=False):
        """Iterate over attributes of a given resource that this references.

        Return an iterator over dependent attributes for specified
        resource_name in the output's value field.
        """
        if self._all_dep_attrs is None and load_all:
            attr_map = collections.defaultdict(set)
            for r, a in function.all_dep_attrs(self._value):
                attr_map[r].add(a)
            self._all_dep_attrs = attr_map

        if self._all_dep_attrs is not None:
            return iter(self._all_dep_attrs.get(resource_name, []))

        return function.dep_attrs(self._value, resource_name)

    def get_value(self):
        """Resolve the value of the output."""
        if self._resolved_value is None:
            self._resolved_value = function.resolve(self._value)
        return self._resolved_value

    def description(self):
        """Return a description of the output."""
        if self._description is None:
            return 'No description given'

        return six.text_type(self._description)

    def render_hot(self):
        def items():
            if self._description is not None:
                yield 'description', self._description
            yield 'value', copy.deepcopy(self._value)
        return dict(items())
