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
import itertools

from heat.common import exception


class CircularDependencyException(exception.OpenstackException):
    message = _("Circular Dependency Found: %(cycle)s")


class Dependencies(object):
    '''Helper class for calculating a dependency graph.'''

    class Node(object):
        def __init__(self, requires=None, required_by=None):
            '''
            Initialise the node, optionally with a set of keys this node
            requires and/or a set of keys that this node is required by.
            '''
            self.require = requires and requires.copy() or set()
            self.satisfy = required_by and required_by.copy() or set()

        def copy(self):
            '''Make a copy of the node.'''
            return Dependencies.Node(self.require, self.satisfy)

        def reverse_copy(self):
            '''Make a copy of the node with the edge directions reversed.'''
            return Dependencies.Node(self.satisfy, self.require)

        def required_by(self, source=None):
            '''
            List the keys that require this node, and optionally add a
            new one
            '''
            if source is not None:
                self.satisfy.add(source)
            return iter(self.satisfy)

        def requires(self, target):
            '''Add a key that this node requires.'''
            self.require.add(target)

        def __isub__(self, target):
            '''Remove a key that this node requires.'''
            self.require.remove(target)
            return self

        def __nonzero__(self):
            '''
            Return True if this node is not a leaf (it requires other nodes)
            '''
            return bool(self.require)

        def stem(self):
            '''Return True if this node is a stem (required by nothing).'''
            return not bool(self.satisfy)

        def disjoint(self):
            '''Return True if this node is both a leaf and a stem.'''
            return (not self) and self.stem()

        def __len__(self):
            '''Count the number of keys required by this node.'''
            return len(self.require)

        def __iter__(self):
            '''Iterate over the keys required by this node.'''
            return iter(self.require)

        def __str__(self):
            '''Return a human-readable string representation of the node.'''
            return '{%s}' % ', '.join(str(n) for n in self)

        def __repr__(self):
            '''Return a string representation of the node.'''
            return repr(self.require)

    def __init__(self, edges=[]):
        '''
        Initialise, optionally with a list of edges, in the form of
        (requirer, required) tuples.
        '''
        self.deps = collections.defaultdict(self.Node)
        for e in edges:
            self += e

    def __iadd__(self, edge):
        '''Add another edge, in the form of a (requirer, required) tuple.'''
        requirer, required = edge

        if required is None:
            # Just ensure the node is created by accessing the defaultdict
            self.deps[requirer]
        else:
            self.deps[required].required_by(requirer)
            self.deps[requirer].requires(required)

        return self

    def __getitem__(self, last):
        '''
        Return a partial dependency graph consisting of the specified node and
        all those that require it only.
        '''
        if last not in self.deps:
            raise KeyError

        def get_edges(key):
            def requirer_edges(rqr):
                # Concatenate the dependency on the current node with the
                # recursive generated list
                return itertools.chain([(rqr, key)], get_edges(rqr))

            # Get the edge list for each node that requires the current node
            edge_lists = itertools.imap(requirer_edges,
                                        self.deps[key].required_by())
            # Combine the lists into one long list
            return itertools.chain.from_iterable(edge_lists)

        if self.deps[last].stem():
            # Nothing requires this, so just add the node itself
            edges = [(last, None)]
        else:
            edges = get_edges(last)

        return Dependencies(edges)

    @staticmethod
    def _deps_to_str(deps):
        '''Convert the given dependency graph to a human-readable string.'''
        pairs = ('%s: %s' % (str(k), str(v)) for k, v in deps.items())
        return '{%s}' % ', '.join(pairs)

    def __str__(self):
        '''
        Return a human-readable string representation of the dependency graph
        '''
        return self._deps_to_str(self.deps)

    def _edges(self):
        '''Return an iterator over all of the edges in the graph.'''
        def outgoing_edges(rqr, node):
            if node.disjoint():
                yield (rqr, None)
            else:
                for rqd in node:
                    yield (rqr, rqd)
        return itertools.chain.from_iterable(outgoing_edges(*item)
                                             for item in self.deps.iteritems())

    def __repr__(self):
        '''Return a string representation of the object.'''
        return 'Dependencies([%s])' % ', '.join(repr(e) for e in self._edges())

    def _toposort(self, deps):
        '''Generate a topological sort of a dependency graph.'''
        def next_leaf():
            for leaf, node in deps.items():
                if not node:
                    return leaf, node

            # There are nodes remaining, but no more leaves: a cycle
            cycle = self._deps_to_str(deps)
            raise CircularDependencyException(cycle=cycle)

        for iteration in xrange(len(deps)):
            leaf, node = next_leaf()
            yield leaf

            # Remove the node and all edges connected to it before continuing
            # to look for more leaves
            for src in node.required_by():
                deps[src] -= leaf
            del deps[leaf]

    def _mapgraph(self, func):
        '''Map the supplied function onto every node in the graph.'''
        return dict((k, func(n)) for k, n in self.deps.items())

    def __iter__(self):
        '''Return a topologically sorted iterator'''
        deps = self._mapgraph(lambda n: n.copy())
        return self._toposort(deps)

    def __reversed__(self):
        '''Return a reverse topologically sorted iterator'''
        rev_deps = self._mapgraph(lambda n: n.reverse_copy())
        return self._toposort(rev_deps)
