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
import itertools
import operator

from heat.common import exception

from heat.engine import function
from heat.engine import properties


__all__ = ['ResourceDefinition']


class ResourceDefinitionCore(object):
    """
    A definition of a resource, independent of any particular template format.
    """

    DELETION_POLICIES = (
        DELETE, RETAIN, SNAPSHOT,
    ) = (
        'Delete', 'Retain', 'Snapshot',
    )

    def __init__(self, name, resource_type, properties=None, metadata=None,
                 depends=None, deletion_policy=None, update_policy=None,
                 description=''):
        """
        Initialise with the parsed definition of a resource.

        Any intrinsic functions present in any of the sections should have been
        parsed into Function objects before constructing the definition.

        :param name: The name of the resource (for use in error messages)
        :param resource_type: The resource type
        :param properties: A dictionary of supplied property values
        :param metadata: The supplied metadata
        :param depends: A list of resource names on which this resource depends
        :param deletion_policy: The deletion policy for the resource
        :param update_policy: A dictionary of supplied update policies
        :param description: A string describing the resource
        """
        depends = depends or []
        self.name = name
        self.resource_type = resource_type
        self.description = description
        self._properties = properties
        self._metadata = metadata
        self._depends = depends
        self._deletion_policy = deletion_policy
        self._update_policy = update_policy

        self._hash = hash(self.resource_type)
        self._rendering = None

        assert isinstance(description, basestring)

        if properties is not None:
            assert isinstance(properties, (collections.Mapping,
                                           function.Function))
            self._hash ^= _hash_data(properties)

        if metadata is not None:
            assert isinstance(metadata, (collections.Mapping,
                                         function.Function))
            self._hash ^= _hash_data(metadata)

        assert isinstance(depends, (collections.Sequence,
                                    function.Function))
        assert not isinstance(depends, basestring)
        self._hash ^= _hash_data(depends)

        if deletion_policy is not None:
            assert deletion_policy in self.DELETION_POLICIES
            self._hash ^= hash(deletion_policy)

        if update_policy is not None:
            assert isinstance(update_policy, (collections.Mapping,
                                              function.Function))
            self._hash ^= _hash_data(update_policy)

    def freeze(self, **overrides):
        """
        Return a frozen resource definition, with all functions resolved.

        This return a new resource definition with fixed data (containing no
        intrinsic functions). Named arguments passed to this method override
        the values passed as arguments to the constructor.
        """
        def arg_item(attr_name):
            name = attr_name.lstrip('_')
            if name in overrides:
                value = overrides[name]
                if not value and getattr(self, attr_name) is None:
                    value = None
            else:
                value = function.resolve(getattr(self, attr_name))

            return name, value

        args = ('name', 'resource_type', '_properties', '_metadata',
                '_depends', '_deletion_policy', '_update_policy',
                'description')

        defn = type(self)(**dict(arg_item(a) for a in args))
        defn._frozen = True
        return defn

    def reparse(self, stack, template):
        """
        Reinterpret the resource definition in the context of a new stack.

        This returns a new resource definition, with all of the functions
        parsed in the context of the specified stack and template.
        """
        assert not getattr(self, '_frozen', False), \
            "Cannot re-parse a frozen definition"

        def reparse_snippet(snippet):
            return template.parse(stack, copy.deepcopy(snippet))

        return type(self)(self.name, self.resource_type,
                          reparse_snippet(self._properties),
                          reparse_snippet(self._metadata),
                          reparse_snippet(self._depends),
                          reparse_snippet(self._deletion_policy),
                          reparse_snippet(self._update_policy))

    def dependencies(self, stack):
        """
        Return the Resource objects in the given stack on which this depends.
        """
        def path(section):
            return '.'.join([self.name, section])

        def get_resource(res_name):
            if res_name not in stack:
                raise exception.InvalidTemplateReference(resource=res_name,
                                                         key=self.name)
            return stack[res_name]

        def strict_func_deps(data, datapath):
            return itertools.ifilter(lambda r: getattr(r, 'strict_dependency',
                                                       True),
                                     function.dependencies(data, datapath))

        return itertools.chain((get_resource(dep) for dep in self._depends),
                               strict_func_deps(self._properties,
                                                path(PROPERTIES)),
                               strict_func_deps(self._metadata,
                                                path(METADATA)))

    def properties(self, schema, context=None):
        """
        Return a Properties object representing the resource properties.

        The Properties object is constructed from the given schema, and may
        require a context to validate constraints.
        """
        return properties.Properties(schema, self._properties or {},
                                     function.resolve, self.name, context)

    def deletion_policy(self):
        """
        Return the deletion policy for the resource.

        The policy will be one of those listed in DELETION_POLICIES.
        """
        return function.resolve(self._deletion_policy) or self.DELETE

    def update_policy(self, schema, context=None):
        """
        Return a Properties object representing the resource update policy.

        The Properties object is constructed from the given schema, and may
        require a context to validate constraints.
        """
        return properties.Properties(schema, self._update_policy or {},
                                     function.resolve, self.name, context)

    def metadata(self):
        """
        Return the resource metadata.
        """
        return function.resolve(self._metadata) or {}

    def render_hot(self):
        """
        Return a HOT snippet for the resource definition.
        """
        if self._rendering is None:
            attrs = {
                'type': 'resource_type',
                'properties': '_properties',
                'metadata': '_metadata',
                'deletion_policy': '_deletion_policy',
                'update_policy': '_update_policy',
                'depends_on': '_depends',
            }

            def rawattrs():
                """Get an attribute with function objects stripped out."""
                for key, attr in attrs.items():
                    value = getattr(self, attr)
                    if value is not None:
                        yield key, copy.deepcopy(value)

            self._rendering = dict(rawattrs())

        return self._rendering

    def __eq__(self, other):
        """
        Compare this resource definition for equality with another.

        Two resource definitions are considered to be equal if they can be
        generated from the same template snippet. The name of the resource is
        ignored, as are the actual values that any included functions resolve
        to.
        """
        if not isinstance(other, ResourceDefinitionCore):
            return NotImplemented

        return self.render_hot() == other.render_hot()

    def __ne__(self, other):
        """
        Compare this resource definition for inequality with another.

        See __eq__() for the definition of equality.
        """
        equal = self.__eq__(other)
        if equal is NotImplemented:
            return NotImplemented

        return not equal

    def __hash__(self):
        """
        Return a hash value for this resource definition.

        Resource definitions that compare equal will have the same hash. (In
        particular, the resource name is *not* taken into account.) See
        the __eq__() method for the definition of equality.
        """
        return self._hash

    def __repr__(self):
        """
        Return a string representation of the resource definition.
        """

        def arg_repr(arg_name):
            return '='.join([arg_name, repr(getattr(self, '_%s' % arg_name))])

        args = ('properties', 'metadata', 'depends',
                'deletion_policy', 'update_policy')
        data = {
            'classname': type(self).__name__,
            'name': repr(self.name),
            'type': repr(self.type),
            'args': ', '.join(arg_repr(n) for n in args)
        }
        return '%(classname)s(%(name)s, %(type)s, %(args)s)' % data


_KEYS = (
    TYPE, PROPERTIES, METADATA, DELETION_POLICY, UPDATE_POLICY,
    DEPENDS_ON, DESCRIPTION,
) = (
    'Type', 'Properties', 'Metadata', 'DeletionPolicy', 'UpdatePolicy',
    'DependsOn', 'Description',
)


class ResourceDefinition(ResourceDefinitionCore, collections.Mapping):
    """
    A resource definition that also acts like a cfn template snippet.

    This class exists only for backwards compatibility with existing resource
    plugins and unit tests; it will at some point be deprecated and then
    replaced with ResourceDefinitionCore.
    """

    def __eq__(self, other):
        """
        Compare this resource definition for equality with another.

        Two resource definitions are considered to be equal if they can be
        generated from the same template snippet. The name of the resource is
        ignored, as are the actual values that any included functions resolve
        to.

        This method can also compare the resource definition to a template
        snippet. In this case, two snippets are considered equal if they
        compare equal in a dictionary comparison. (Specifically, this means
        that intrinsic functions are compared by their results.) This exists
        solely to not break existing unit tests.
        """
        if not isinstance(other, ResourceDefinitionCore):
            if isinstance(other, collections.Mapping):
                return dict(self) == other

        return super(ResourceDefinition, self).__eq__(other)

    def __iter__(self):
        """
        Iterate over the available CFN template keys.

        This is for backwards compatibility with existing code that expects a
        parsed-JSON template snippet.
        """
        yield TYPE
        if self._properties is not None:
            yield PROPERTIES
        if self._metadata is not None:
            yield METADATA
        if self._deletion_policy is not None:
            yield DELETION_POLICY
        if self._update_policy is not None:
            yield UPDATE_POLICY
        if self._depends:
            yield DEPENDS_ON
        if self.description:
            yield DESCRIPTION

    def __getitem__(self, key):
        """
        Get the specified item from a CFN template snippet.

        This is for backwards compatibility with existing code that expects a
        parsed-JSON template snippet.
        """
        if key == TYPE:
            return self.resource_type
        elif key == PROPERTIES:
            if self._properties is not None:
                return self._properties
        elif key == METADATA:
            if self._metadata is not None:
                return self._metadata
        elif key == DELETION_POLICY:
            if self._deletion_policy is not None:
                return self._deletion_policy
        elif key == UPDATE_POLICY:
            if self._update_policy is not None:
                return self._update_policy
        elif key == DEPENDS_ON:
            if self._depends:
                if len(self._depends) == 1:
                    return self._depends[0]
                return self._depends
        elif key == DESCRIPTION:
            if self.description:
                return self.description

        raise KeyError(key)

    def __len__(self):
        """
        Return the number of available CFN template keys.

        This is for backwards compatibility with existing code that expects a
        parsed-JSON template snippet.
        """
        return len(list(iter(self)))

    def __repr__(self):
        """
        Return a string representation of the resource definition.
        """
        return 'ResourceDefinition %s' % repr(dict(self))


def _hash_data(data):
    """
    Return a stable hash value for an arbitrary parsed-JSON data snippet.
    """
    if isinstance(data, function.Function):
        data = copy.deepcopy(data)

    if not isinstance(data, basestring):
        if isinstance(data, collections.Sequence):
            return hash(tuple(_hash_data(d) for d in data))

        if isinstance(data, collections.Mapping):
            item_hashes = (hash(k) ^ _hash_data(v) for k, v in data.items())
            return reduce(operator.xor, item_hashes, 0L)

    return hash(data)
