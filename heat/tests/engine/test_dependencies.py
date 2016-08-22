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


from heat.engine import dependencies
from heat.tests import common


class dependenciesTest(common.HeatTestCase):

    def _dep_test(self, func, checkorder, deps):
        nodes = set.union(*[set(e) for e in deps])

        d = dependencies.Dependencies(deps)
        order = list(func(d))

        for n in nodes:
            self.assertIn(n, order, '"%s" is not in the sequence' % n)
            self.assertEqual(1, order.count(n))

        self.assertEqual(len(nodes), len(order))

        for l, f in deps:
            checkorder(order.index(f), order.index(l))

    def _dep_test_fwd(self, *deps):
        def assertLess(a, b):
            self.assertTrue(a < b,
                            '"%s" is not less than "%s"' % (str(a), str(b)))
        self._dep_test(iter, assertLess, deps)

    def _dep_test_rev(self, *deps):
        def assertGreater(a, b):
            self.assertTrue(a > b,
                            '"%s" is not greater than "%s"' % (str(a), str(b)))
        self._dep_test(reversed, assertGreater, deps)

    def test_edges(self):
        input_edges = [('1', None), ('2', '3'), ('2', '4')]
        dp = dependencies.Dependencies(input_edges)
        self.assertEqual(set(input_edges), set(dp.graph().edges()))

    def test_repr(self):
        dp = dependencies.Dependencies([('1', None), ('2', '3'), ('2', '4')])
        s = "Dependencies([('1', None), ('2', '3'), ('2', '4')])"
        self.assertEqual(s, repr(dp))

    def test_single_node(self):
        d = dependencies.Dependencies([('only', None)])
        l = list(iter(d))
        self.assertEqual(1, len(l))
        self.assertEqual('only', l[0])

    def test_disjoint(self):
        d = dependencies.Dependencies([('1', None), ('2', None)])
        l = list(iter(d))
        self.assertEqual(2, len(l))
        self.assertIn('1', l)
        self.assertIn('2', l)

    def test_single_fwd(self):
        self._dep_test_fwd(('second', 'first'))

    def test_single_rev(self):
        self._dep_test_rev(('second', 'first'))

    def test_chain_fwd(self):
        self._dep_test_fwd(('third', 'second'), ('second', 'first'))

    def test_chain_rev(self):
        self._dep_test_rev(('third', 'second'), ('second', 'first'))

    def test_diamond_fwd(self):
        self._dep_test_fwd(('last', 'mid1'), ('last', 'mid2'),
                           ('mid1', 'first'), ('mid2', 'first'))

    def test_diamond_rev(self):
        self._dep_test_rev(('last', 'mid1'), ('last', 'mid2'),
                           ('mid1', 'first'), ('mid2', 'first'))

    def test_complex_fwd(self):
        self._dep_test_fwd(('last', 'mid1'), ('last', 'mid2'),
                           ('mid1', 'mid3'), ('mid1', 'first'),
                           ('mid3', 'first'), ('mid2', 'first'))

    def test_complex_rev(self):
        self._dep_test_rev(('last', 'mid1'), ('last', 'mid2'),
                           ('mid1', 'mid3'), ('mid1', 'first'),
                           ('mid3', 'first'), ('mid2', 'first'))

    def test_many_edges_fwd(self):
        self._dep_test_fwd(('last', 'e1'), ('last', 'mid1'), ('last', 'mid2'),
                           ('mid1', 'e2'), ('mid1', 'mid3'),
                           ('mid2', 'mid3'),
                           ('mid3', 'e3'))

    def test_many_edges_rev(self):
        self._dep_test_rev(('last', 'e1'), ('last', 'mid1'), ('last', 'mid2'),
                           ('mid1', 'e2'), ('mid1', 'mid3'),
                           ('mid2', 'mid3'),
                           ('mid3', 'e3'))

    def test_dbldiamond_fwd(self):
        self._dep_test_fwd(('last', 'a1'), ('last', 'a2'),
                           ('a1', 'b1'), ('a2', 'b1'), ('a2', 'b2'),
                           ('b1', 'first'), ('b2', 'first'))

    def test_dbldiamond_rev(self):
        self._dep_test_rev(('last', 'a1'), ('last', 'a2'),
                           ('a1', 'b1'), ('a2', 'b1'), ('a2', 'b2'),
                           ('b1', 'first'), ('b2', 'first'))

    def test_circular_fwd(self):
        d = dependencies.Dependencies([('first', 'second'),
                                       ('second', 'third'),
                                       ('third', 'first')])
        self.assertRaises(dependencies.CircularDependencyException,
                          list,
                          iter(d))

    def test_circular_rev(self):
        d = dependencies.Dependencies([('first', 'second'),
                                       ('second', 'third'),
                                       ('third', 'first')])
        self.assertRaises(dependencies.CircularDependencyException,
                          list,
                          reversed(d))

    def test_self_ref(self):
        d = dependencies.Dependencies([('node', 'node')])
        self.assertRaises(dependencies.CircularDependencyException,
                          list,
                          iter(d))

    def test_complex_circular_fwd(self):
        d = dependencies.Dependencies([('last', 'e1'), ('last', 'mid1'),
                                       ('last', 'mid2'), ('mid1', 'e2'),
                                       ('mid1', 'mid3'), ('mid2', 'mid3'),
                                       ('mid3', 'e3'), ('e3', 'mid1')])
        self.assertRaises(dependencies.CircularDependencyException,
                          list,
                          iter(d))

    def test_complex_circular_rev(self):
        d = dependencies.Dependencies([('last', 'e1'), ('last', 'mid1'),
                                       ('last', 'mid2'), ('mid1', 'e2'),
                                       ('mid1', 'mid3'), ('mid2', 'mid3'),
                                       ('mid3', 'e3'), ('e3', 'mid1')])
        self.assertRaises(dependencies.CircularDependencyException,
                          list,
                          reversed(d))

    def test_noexist_partial(self):
        d = dependencies.Dependencies([('foo', 'bar')])

        def get(i):
            return d[i]
        self.assertRaises(KeyError, get, 'baz')

    def test_single_partial(self):
        d = dependencies.Dependencies([('last', 'first')])
        p = d['last']
        l = list(iter(p))
        self.assertEqual(1, len(l))
        self.assertEqual('last', l[0])

    def test_simple_partial(self):
        d = dependencies.Dependencies([('last', 'middle'),
                                       ('middle', 'first')])
        p = d['middle']
        order = list(iter(p))
        self.assertEqual(2, len(order))
        for n in ('last', 'middle'):
            self.assertIn(n, order,
                          "'%s' not found in dependency order" % n)
        self.assertGreater(order.index('last'), order.index('middle'))

    def test_simple_multilevel_partial(self):
        d = dependencies.Dependencies([('last', 'middle'),
                                       ('middle', 'target'),
                                       ('target', 'first')])
        p = d['target']
        order = list(iter(p))
        self.assertEqual(3, len(order))
        for n in ('last', 'middle', 'target'):
            self.assertIn(n, order,
                          "'%s' not found in dependency order" % n)

    def test_complex_partial(self):
        d = dependencies.Dependencies([('last', 'e1'), ('last', 'mid1'),
                                       ('last', 'mid2'), ('mid1', 'e2'),
                                       ('mid1', 'mid3'), ('mid2', 'mid3'),
                                       ('mid3', 'e3')])
        p = d['mid3']
        order = list(iter(p))
        self.assertEqual(4, len(order))
        for n in ('last', 'mid1', 'mid2', 'mid3'):
            self.assertIn(n, order,
                          "'%s' not found in dependency order" % n)

    def test_required_by(self):
        d = dependencies.Dependencies([('last', 'e1'), ('last', 'mid1'),
                                       ('last', 'mid2'), ('mid1', 'e2'),
                                       ('mid1', 'mid3'), ('mid2', 'mid3'),
                                       ('mid3', 'e3')])

        self.assertEqual(0, len(list(d.required_by('last'))))

        required_by = list(d.required_by('mid3'))
        self.assertEqual(2, len(required_by))
        for n in ('mid1', 'mid2'):
            self.assertIn(n, required_by,
                          "'%s' not found in required_by" % n)

        required_by = list(d.required_by('e2'))
        self.assertEqual(1, len(required_by))
        self.assertIn('mid1', required_by,
                      "'%s' not found in required_by" % n)

        self.assertRaises(KeyError, d.required_by, 'foo')

    def test_leaves(self):
        d = dependencies.Dependencies([('last1', 'mid'), ('last2', 'mid'),
                                       ('mid', 'first1'), ('mid', 'first2')])

        leaves = sorted(list(d.leaves()))

        self.assertEqual(['first1', 'first2'], leaves)

    def test_roots(self):
        d = dependencies.Dependencies([('last1', 'mid'), ('last2', 'mid'),
                                       ('mid', 'first1'), ('mid', 'first2')])

        leaves = sorted(list(d.roots()))

        self.assertEqual(['last1', 'last2'], leaves)
