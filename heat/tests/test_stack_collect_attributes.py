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

import itertools
import six

from heat.common import template_format
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


tmpl1 = """
heat_template_version: 2014-10-16
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
"""

tmpl2 = """
heat_template_version: 2014-10-16
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
  BResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, attr_A1]}
    metadata:
      Foo:  {get_attr: [AResource, attr_A1]}
outputs:
  out1:
    value: {get_attr: [AResource, attr_A1]}
"""

tmpl3 = """
heat_template_version: 2014-10-16
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
  BResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, attr_A1]}
      Doo:  {get_attr: [AResource, attr_A2]}
      Bar:  {get_attr: [AResource, attr_A3]}
    metadata:
      first:  {get_attr: [AResource, meta_A1]}
      second:  {get_attr: [AResource, meta_A2]}
      third:  {get_attr: [AResource, attr_A3]}
outputs:
  out1:
    value: {get_attr: [AResource, out_A1]}
  out2:
    value: {get_attr: [AResource, out_A2]}
"""

tmpl4 = """
heat_template_version: 2014-10-16
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
  BResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
  CResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
  DResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, attr_A1]}
      Doo:  {get_attr: [BResource, attr_B1]}
    metadata:
      Doo:  {get_attr: [CResource, attr_C1]}
outputs:
  out1:
    value: [{get_attr: [AResource, attr_A1]},
            {get_attr: [BResource, attr_B1]},
            {get_attr: [CResource, attr_C1]}]
"""

tmpl5 = """
heat_template_version: 2014-10-16
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
  BResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, attr_A1]}
      Doo:  {get_attr: [AResource, attr_A2]}
    metadata:
      first:  {get_attr: [AResource, meta_A1]}
  CResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, attr_A1]}
      Doo:  {get_attr: [BResource, attr_B2]}
    metadata:
      Doo:  {get_attr: [BResource, attr_B1]}
      first:  {get_attr: [AResource, meta_A1]}
      second:  {get_attr: [BResource, meta_B2]}
outputs:
  out1:
    value: [{get_attr: [AResource, attr_A3]},
            {get_attr: [AResource, attr_A4]},
            {get_attr: [BResource, attr_B3]}]
"""

tmpl6 = """
heat_template_version: 2015-04-30
resources:
  AResource:
    type: ResourceWithComplexAttributesType
  BResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, list, 1]}
      Doo:  {get_attr: [AResource, nested_dict, dict, b]}
outputs:
  out1:
    value: [{get_attr: [AResource, flat_dict, key2]},
            {get_attr: [AResource, nested_dict, string]},
            {get_attr: [BResource, attr_B3]}]
  out2:
    value: {get_resource: BResource}
"""

tmpl7 = """
heat_template_version: 2015-10-15
resources:
  AResource:
    type: ResourceWithPropsType
    properties:
      Foo: 'abc'
  BResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, attr_A1]}
      Doo:  {get_attr: [AResource, attr_A2]}
    metadata:
      first:  {get_attr: [AResource, meta_A1]}
  CResource:
    type: ResourceWithPropsType
    properties:
      Foo:  {get_attr: [AResource, attr_A1]}
      Doo:  {get_attr: [BResource, attr_B2]}
    metadata:
      Doo:  {get_attr: [BResource, attr_B1]}
      first:  {get_attr: [AResource, meta_A1]}
      second:  {get_attr: [BResource, meta_B2]}
outputs:
  out1:
    value: [{get_attr: [AResource, attr_A3]},
            {get_attr: [AResource, attr_A4]},
            {get_attr: [BResource, attr_B3]},
            {get_attr: [CResource]}]
"""


class DepAttrsTest(common.HeatTestCase):

    scenarios = [
        ('no_attr',
            dict(tmpl=tmpl1,
                 expected={'AResource': set()})),
        ('one_res_one_attr',
            dict(tmpl=tmpl2,
                 expected={'AResource': {'attr_A1'},
                           'BResource': set()})),
        ('one_res_several_attrs',
            dict(tmpl=tmpl3,
                 expected={'AResource': {'attr_A1', 'attr_A2', 'attr_A3',
                                         'meta_A1', 'meta_A2'},
                           'BResource': set()})),
        ('several_res_one_attr',
            dict(tmpl=tmpl4,
                 expected={'AResource': {'attr_A1'},
                           'BResource': {'attr_B1'},
                           'CResource': {'attr_C1'},
                           'DResource': set()})),
        ('several_res_several_attrs',
            dict(tmpl=tmpl5,
                 expected={'AResource': {'attr_A1', 'attr_A2', 'meta_A1'},
                           'BResource': {'attr_B1', 'attr_B2', 'meta_B2'},
                           'CResource': set()})),
        ('nested_attr',
            dict(tmpl=tmpl6,
                 expected={'AResource': set([(u'list', 1),
                                             (u'nested_dict', u'dict', u'b')]),
                           'BResource': set([])})),
        ('several_res_several_attrs_and_all_attrs',
            dict(tmpl=tmpl7,
                 expected={'AResource': {'attr_A1', 'attr_A2', 'meta_A1'},
                           'BResource': {'attr_B1', 'attr_B2', 'meta_B2'},
                           'CResource': set()}))
    ]

    def setUp(self):
        super(DepAttrsTest, self).setUp()
        self.ctx = utils.dummy_context()

        self.parsed_tmpl = template_format.parse(self.tmpl)
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(self.parsed_tmpl))

    def test_dep_attrs(self):
        for res in six.itervalues(self.stack):
            definitions = (self.stack.defn.resource_definition(n)
                           for n in self.parsed_tmpl['resources'])
            self.assertEqual(self.expected[res.name],
                             set(itertools.chain.from_iterable(
                                 d.dep_attrs(res.name) for d in definitions)))

    def test_all_dep_attrs(self):
        for res in six.itervalues(self.stack):
            definitions = (self.stack.defn.resource_definition(n)
                           for n in self.parsed_tmpl['resources'])
            attrs = set(itertools.chain.from_iterable(
                d.dep_attrs(res.name, load_all=True) for d in definitions))
            self.assertEqual(self.expected[res.name], attrs)


class ReferencedAttrsTest(common.HeatTestCase):
    def setUp(self):
        super(ReferencedAttrsTest, self).setUp()
        parsed_tmpl = template_format.parse(tmpl6)
        self.stack = stack.Stack(utils.dummy_context(), 'test_stack',
                                 template.Template(parsed_tmpl))
        self.resA = self.stack['AResource']
        self.resB = self.stack['BResource']

    def test_referenced_attrs_resources(self):
        self.assertEqual(self.resA.referenced_attrs(in_resources=True,
                                                    in_outputs=False),
                         {('list', 1), ('nested_dict', 'dict', 'b')})
        self.assertEqual(self.resB.referenced_attrs(in_resources=True,
                                                    in_outputs=False),
                         set())

    def test_referenced_attrs_outputs(self):
        self.assertEqual(self.resA.referenced_attrs(in_resources=False,
                                                    in_outputs=True),
                         {('flat_dict', 'key2'), ('nested_dict', 'string')})
        self.assertEqual(self.resB.referenced_attrs(in_resources=False,
                                                    in_outputs=True),
                         {'attr_B3'})

    def test_referenced_attrs_single_output(self):
        self.assertEqual(self.resA.referenced_attrs(in_resources=False,
                                                    in_outputs={'out1'}),
                         {('flat_dict', 'key2'), ('nested_dict', 'string')})
        self.assertEqual(self.resB.referenced_attrs(in_resources=False,
                                                    in_outputs={'out1'}),
                         {'attr_B3'})

        self.assertEqual(self.resA.referenced_attrs(in_resources=False,
                                                    in_outputs={'out2'}),
                         set())
        self.assertEqual(self.resB.referenced_attrs(in_resources=False,
                                                    in_outputs={'out2'}),
                         set())

    def test_referenced_attrs_outputs_list(self):
        self.assertEqual(self.resA.referenced_attrs(in_resources=False,
                                                    in_outputs={'out1',
                                                                'out2'}),
                         {('flat_dict', 'key2'), ('nested_dict', 'string')})
        self.assertEqual(self.resB.referenced_attrs(in_resources=False,
                                                    in_outputs={'out1',
                                                                'out2'}),
                         {'attr_B3'})

    def test_referenced_attrs_both(self):
        self.assertEqual(self.resA.referenced_attrs(in_resources=True,
                                                    in_outputs=True),
                         {('list', 1), ('nested_dict', 'dict', 'b'),
                          ('flat_dict', 'key2'), ('nested_dict', 'string')})
        self.assertEqual(self.resB.referenced_attrs(in_resources=True,
                                                    in_outputs=True),
                         {'attr_B3'})
