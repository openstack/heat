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

from heat.common import exception
from heat.common.i18n import _


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

    def _repr_result(self):
        try:
            return repr(self.result())
        except (TypeError, ValueError):
            return '???'

    def __repr__(self):
        """Return a string representation of the function.

        The representation includes the function name, arguments and result
        (if available), as well as the name of the function class.
        """
        fntype = type(self)
        classname = '.'.join(filter(None,
                                    (getattr(fntype,
                                             attr,
                                             '') for attr in ('__module__',
                                                              '__name__'))))
        return '<%s {%s: %r} -> %s>' % (classname,
                                        self.fn_name, self.args,
                                        self._repr_result())

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

    __hash__ = None


@six.add_metaclass(abc.ABCMeta)
class Macro(Function):
    """Abstract base class for template macros.

    A macro differs from a function in that it controls how the template is
    parsed. As such, it operates on the syntax tree itself, not on the parsed
    output.
    """
    def __init__(self, stack, fn_name, raw_args, parse_func, template):
        """Initialise with the argument syntax tree and parser function."""
        super(Macro, self).__init__(stack, fn_name, raw_args)
        self._tmplref = weakref.ref(template) if template is not None else None
        self.parsed = self.parse_args(parse_func)

    @property
    def template(self):
        ref = self._tmplref
        if ref is None:
            return None

        tmpl = ref()
        assert tmpl is not None, "Need a reference to the Template object"
        return tmpl

    @abc.abstractmethod
    def parse_args(self, parse_func):
        """Parse the macro using the supplied parsing function.

        Macro subclasses should override this method to control parsing of
        the arguments.
        """
        return parse_func(self.args)

    def validate(self):
        """Validate arguments without resolving the result."""
        validate(self.parsed)

    def result(self):
        """Return the resolved result of the macro contents."""
        return resolve(self.parsed)

    def dependencies(self, path):
        return dependencies(self.parsed, '.'.join([path, self.fn_name]))

    def dep_attrs(self, resource_name):
        """Return the attributes of the specified resource that are referenced.

        Return an iterator over any attributes of the specified resource that
        this function references.
        """
        return dep_attrs(self.parsed, resource_name)

    def __reduce__(self):
        """Return a representation of the macro result suitable for pickling.

        This allows the copy module (which works by pickling and then
        unpickling objects) to copy a template. Functions in the copy will
        return to their original (JSON) form (i.e. a single-element map).

        Unlike other functions, macros are *not* preserved during a copy. The
        the processed (but unparsed) output is returned in their place.
        """
        if isinstance(self.parsed, Function):
            return self.parsed.__reduce__()
        return type(self.parsed), (self.parsed,)

    def _repr_result(self):
        return repr(self.parsed)


def resolve(snippet):
    if isinstance(snippet, Function):
        return snippet.result()

    if isinstance(snippet, collections.Mapping):
        return dict((k, resolve(v)) for k, v in snippet.items())
    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):
        return [resolve(v) for v in snippet]

    return snippet


def validate(snippet, path=''):
    if isinstance(snippet, Function):
        try:
            snippet.validate()
        except AssertionError:
            raise
        except Exception as e:
            path = '.'.join([path, snippet.fn_name])
            raise exception.StackValidationFailed(
                path=path, message=six.text_type(e))
    elif isinstance(snippet, collections.Mapping):
        def mkpath(key):
            return '.'.join([path, key])

        for k, v in six.iteritems(snippet):
            validate(v, mkpath(k))
    elif (not isinstance(snippet, six.string_types) and
          isinstance(snippet, collections.Iterable)):
        def mkpath(indx):
            return '.'.join([path, '[%d]' % indx])

        for i, v in enumerate(snippet):
            validate(v, mkpath(i))


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


class Invalid(Function):
    """A function for checking condition functions and to force failures.

    This function is used to force failures for functions that are not
    supported in condition definition.
    """

    def __init__(self, stack, fn_name, args):
        raise ValueError(_('The function "%s" '
                           'is invalid in this context') % fn_name)

    def result(self):
        return super(Invalid, self).result()
