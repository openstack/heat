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

import abc
import collections
import itertools
import weakref

import six


@six.add_metaclass(abc.ABCMeta)
class Function(object):
    """Abstract base class for template functions."""

    def __init__(self, stack, fn_name, args):
        """Initialise with a Stack, the function name and the arguments.

        All functions take the form of a single-item map in JSON::

            { <fn_name> : <args> }
        """
        super(Function, self).__init__()
        self._stackref = weakref.ref(stack) if stack is not None else None
        self.fn_name = fn_name
        self.args = args

    @property
    def stack(self):
        ref = self._stackref
        if ref is None:
            return None

        stack = ref()
        assert stack is not None, "Need a reference to the Stack object"
        return stack

    def validate(self):
        """Validate arguments without resolving the function.

        Function subclasses must override this method to validate their
        args.
        """
        validate(self.args)

    @abc.abstractmethod
    def result(self):
        """Return the result of resolving the function.

        Function subclasses must override this method to calculate their
        results.
        """
        return {self.fn_name: self.args}

    def dependencies(self, path):
        return dependencies(self.args, '.'.join([path, self.fn_name]))

    def dep_attrs(self, resource_name):
        """Return the attributes of the specified resource that are referenced.

        Return an iterator over any attributes of the specified resource that
        this function references.
        """
        return dep_attrs(self.args, resource_name)

    def __reduce__(self):
        """Return a representation of the function suitable for pickling.

        This allows the copy module (which works by pickling and then
        unpickling objects) to copy a template. Functions in the copy will
        return to their original (JSON) form (i.e. a single-element map).
        """
        return dict, ([(self.fn_name, self.args)],)

    def __repr__(self):
        """Return a string representation of the function.

        The representation includes the function name, arguments and result
        (if available), as well as the name of the function class.
        """
        try:
            result = repr(self.result())
        except (TypeError, ValueError):
            result = '???'

        fntype = type(self)
        classname = '.'.join(filter(None,
                                    (getattr(fntype,
                                             attr,
                                             '') for attr in ('__module__',
                                                              '__name__'))))
        return '<%s {%s: %r} -> %s>' % (classname,
                                        self.fn_name, self.args,
                                        result)

    def __eq__(self, other):
        """Compare the result of this function for equality."""
        try:
            result = self.result()

            if isinstance(other, Function):
                return result == other.result()
            else:
                return result == other

        except (TypeError, ValueError):
            return NotImplemented

    def __ne__(self, other):
        """Compare the result of this function for inequality."""
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return NotImplemented
        return not eq

    def __hash__(self):
        return id(self)


def resolve(snippet):
    while isinstance(snippet, Function):
        snippet = snippet.result()

    if isinstance(snippet, collections.Mapping):
        return dict((k, resolve(v)) for k, v in snippet.items())
    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):
        return [resolve(v) for v in snippet]

    return snippet


def validate(snippet):
    if isinstance(snippet, Function):
        snippet.validate()
    elif isinstance(snippet, collections.Mapping):
        for v in six.itervalues(snippet):
            validate(v)
    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):
        for v in snippet:
            validate(v)


def dependencies(snippet, path=''):
    """Return an iterator over Resource dependencies in a template snippet.

    The snippet should be already parsed to insert Function objects where
    appropriate.
    """

    if isinstance(snippet, Function):
        return snippet.dependencies(path)

    elif isinstance(snippet, collections.Mapping):
        def mkpath(key):
            return '.'.join([path, six.text_type(key)])

        deps = (dependencies(value,
                             mkpath(key)) for key, value in snippet.items())
        return itertools.chain.from_iterable(deps)

    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):
        def mkpath(idx):
            return ''.join([path, '[%d]' % idx])

        deps = (dependencies(value,
                             mkpath(i)) for i, value in enumerate(snippet))
        return itertools.chain.from_iterable(deps)

    else:
        return []


def dep_attrs(snippet, resource_name):
    """Iterator over dependent attrs of a resource in a template snippet.

    The snippet should be already parsed to insert Function objects where
    appropriate.

    :returns: an iterator over the attributes of the specified resource that
    are referenced in the template snippet.
    """

    if isinstance(snippet, Function):
        return snippet.dep_attrs(resource_name)

    elif isinstance(snippet, collections.Mapping):
        attrs = (dep_attrs(value, resource_name) for value in snippet.items())
        return itertools.chain.from_iterable(attrs)
    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):
        attrs = (dep_attrs(value, resource_name) for value in snippet)
        return itertools.chain.from_iterable(attrs)
    return []
