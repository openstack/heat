
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

from six.moves import xrange

from heat.common import exception

from heat.openstack.common.gettextutils import _


class CircularDependencyException(exception.HeatException):
    msg_fmt = _("Circular Dependency Found: %(cycle)s")


class Node(object):
    '''A node in a dependency graph.'''

    def __init__(self, requires=None, required_by=None):
        '''
        Initialise the node, optionally with a set of keys this node
        requires and/or a set of keys that this node is required by.
        '''
        self.require = requires and requires.copy() or set()
        self.satisfy = required_by and required_by.copy() or set()

    def copy(self):
        '''Return a copy of the node.'''
        return Node(self.require, self.satisfy)

    def reverse_copy(self):
        '''Return a copy of the node with the edge directions reversed.'''
        return Node(self.satisfy, self.require)

    def required_by(self, source=None):
        '''
        List the keys that require this node, and optionally add a
        new one.
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
        '''Return True if this node is not a leaf (it requires other nodes).'''
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


class Graph(collections.defaultdict):
    '''A mutable mapping of objects to nodes in a dependency graph.'''

    def __init__(self, *args):
        super(Graph, self).__init__(Node, *args)

    def map(self, func):
        '''
        Return a dictionary derived from mapping the supplied function onto
        each node in the graph.
        '''
        return dict((k, func(n)) for k, n in self.items())

    def copy(self):
        '''Return a copy of the graph.'''
        return Graph(self.map(lambda n: n.copy()))

    def reverse_copy(self):
        '''Return a copy of the graph with the edges reversed.'''
        return Graph(self.map(lambda n: n.reverse_copy()))

    def edges(self):
        '''Return an iterator over all of the edges in the graph.'''
        def outgoing_edges(rqr, node):
            if node.disjoint():
                yield (rqr, None)
            else:
                for rqd in node:
                    yield (rqr, rqd)
        return itertools.chain.from_iterable(outgoing_edges(*i)
                                             for i in self.iteritems())

    def __delitem__(self, key):
        '''Delete the node given by the specified key from the graph.'''
        node = self[key]

        for src in node.required_by():
            src_node = self[src]
            if key in src_node:
                src_node -= key

        return super(Graph, self).__delitem__(key)

    def __str__(self):
        '''Convert the graph to a human-readable string.'''
        pairs = ('%s: %s' % (str(k), str(v)) for k, v in self.iteritems())
        return '{%s}' % ', '.join(pairs)

    @staticmethod
    def toposort(graph):
        '''
        Return a topologically sorted iterator over a dependency graph.

        This is a destructive operation for the graph.
        '''
        for iteration in xrange(len(graph)):
            for key, node in graph.iteritems():
                if not node:
                    yield key
                    del graph[key]
                    break
            else:
                # There are nodes remaining, but none without
                # dependencies: a cycle
                raise CircularDependencyException(cycle=str(graph))


class Dependencies(object):
    '''Helper class for calculating a dependency graph.'''

    def __init__(self, edges=[]):
        '''
        Initialise, optionally with a list of edges, in the form of
        (requirer, required) tuples.
        '''
        self._graph = Graph()
        for e in edges:
            self += e

    def __iadd__(self, edge):
        '''Add another edge, in the form of a (requirer, required) tuple.'''
        requirer, required = edge

        if required is None:
            # Just ensure the node is created by accessing the defaultdict
            self._graph[requirer]
        else:
            self._graph[required].required_by(requirer)
            self._graph[requirer].requires(required)

        return self

    def required_by(self, last):
        '''
        List the keys that require the specified node.
        '''
        if last not in self._graph:
            raise KeyError

        return self._graph[last].required_by()

    def __getitem__(self, last):
        '''
        Return a partial dependency graph consisting of the specified node and
        all those that require it only.
        '''
        if last not in self._graph:
            raise KeyError

        def get_edges(key):
            def requirer_edges(rqr):
                # Concatenate the dependency on the current node with the
                # recursive generated list
                return itertools.chain([(rqr, key)], get_edges(rqr))

            # Get the edge list for each node that requires the current node
            edge_lists = itertools.imap(requirer_edges,
                                        self._graph[key].required_by())
            # Combine the lists into one long list
            return itertools.chain.from_iterable(edge_lists)

        if self._graph[last].stem():
            # Nothing requires this, so just add the node itself
            edges = [(last, None)]
        else:
            edges = get_edges(last)

        return Dependencies(edges)

    def __str__(self):
        '''
        Return a human-readable string representation of the dependency graph
        '''
        return str(self._graph)

    def __repr__(self):
        '''Return a string representation of the object.'''
        edge_reprs = (repr(e) for e in self._graph.edges())
        return 'Dependencies([%s])' % ', '.join(edge_reprs)

    def graph(self, reverse=False):
        '''Return a copy of the underlying dependency graph.'''
        if reverse:
            return self._graph.reverse_copy()
        else:
            return self._graph.copy()

    def __iter__(self):
        '''Return a topologically sorted iterator'''
        return Graph.toposort(self.graph())

    def __reversed__(self):
        '''Return a reverse topologically sorted iterator'''
        return Graph.toposort(self.graph(reverse=True))
