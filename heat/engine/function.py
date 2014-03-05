
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


class Function(object):
    """
    Abstract base class for template functions.
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self, stack, fn_name, args):
        """
        Initialise with a Stack, the function name and the arguments.

        All functions take the form of a single-item map in JSON::

            { <fn_name> : <args> }
        """
        super(Function, self).__init__()
        self.stack = stack
        self.fn_name = fn_name
        self.args = args

    @abc.abstractmethod
    def result(self):
        """
        Return the result of resolving the function.

        Function subclasses must override this method to calculate their
        results.
        """
        return {self.fn_name: self.args}

    def __reduce__(self):
        """
        Return a representation of the function suitable for pickling.

        This allows the copy module (which works by pickling and then
        unpickling objects) to copy a template. Functions in the copy will
        return to their original (JSON) form (i.e. a single-element map).
        """
        return dict, ([(self.fn_name, self.args)],)

    def __repr__(self):
        """
        Return a string representation of the function.

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


def resolve(snippet):
    while isinstance(snippet, Function):
        snippet = snippet.result()

    if isinstance(snippet, collections.Mapping):
        return dict((k, resolve(v)) for k, v in snippet.items())
    elif (not isinstance(snippet, basestring) and
          isinstance(snippet, collections.Iterable)):
        return [resolve(v) for v in snippet]

    return snippet
