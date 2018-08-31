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

import copy
import json

from heat.common import exception
from heat.common import template_format
from heat.engine import environment
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class TestValue(common.HeatTestCase):

    simple_template = '''
heat_template_version: '2016-10-14'
parameters:
  param1:
    type: <the type>
resources:
  my_value:
    type: OS::Heat::Value
    properties:
      value: {get_param: param1}
  my_value2:
    type: OS::Heat::Value
    properties:
      value: {get_attr: [my_value, value]}
outputs:
  myout:
    value: {get_attr: [my_value2, value]}
'''

    def get_strict_and_loose_templates(self, param_type):
        template_loose = template_format.parse(self.simple_template)
        template_loose['parameters']['param1']['type'] = param_type
        template_strict = copy.deepcopy(template_loose)
        template_strict['resources']['my_value']['properties']['type'] \
            = param_type
        template_strict['resources']['my_value2']['properties']['type'] \
            = param_type
        return (template_strict, template_loose)

    def parse_stack(self, templ_obj):
        stack_name = 'test_value_stack'
        stack = parser.Stack(utils.dummy_context(), stack_name, templ_obj)
        stack.validate()
        stack.store()
        return stack

    def create_stack(self, templ, env=None):
        if isinstance(templ, str):
            return self.create_stack(template_format.parse(templ), env=env)
        if isinstance(templ, dict):
            tmpl_obj = template.Template(templ, env=env)
            return self.create_stack(tmpl_obj)
        assert isinstance(templ, template.Template)
        stack = self.parse_stack(templ)
        self.assertIsNone(stack.create())
        return stack


class TestValueSimple(TestValue):

    scenarios = [
        ('boolean', dict(
            param1=True, param_type="boolean")),
        ('list', dict(
            param1=['a', 'b', 'Z'], param_type="comma_delimited_list")),
        ('map', dict(
            param1={'a': 'Z', 'B': 'y'}, param_type="json")),
        ('number-int', dict(
            param1=-11, param_type="number")),
        ('number-float', dict(
            param1=100.999, param_type="number")),
        ('string', dict(
            param1='Perchance to dream', param_type="string")),
    ]

    def test_value(self):
        ts, tl = self.get_strict_and_loose_templates(self.param_type)
        env = environment.Environment({
            'parameters': {'param1': self.param1}})

        for templ_dict in [ts, tl]:
            stack = self.create_stack(templ_dict, env)
            self.assertEqual(self.param1, stack['my_value'].FnGetAtt('value'))
            self.assertEqual(self.param1, stack['my_value2'].FnGetAtt('value'))
            stack._update_all_resource_data(False, True)
            self.assertEqual(self.param1, stack.outputs['myout'].get_value())


class TestValueLessSimple(TestValue):

    template_bad = '''
heat_template_version: '2016-10-14'
parameters:
  param1:
    type: json
resources:
  my_value:
    type: OS::Heat::Value
    properties:
      value: {get_param: param1}
      type: number
'''

    template_map = '''
heat_template_version: '2016-10-14'
parameters:
  param1:
    type: json
  param2:
    type: json
resources:
  my_value:
    type: OS::Heat::Value
    properties:
      value: {get_param: param1}
      type: json
  my_value2:
    type: OS::Heat::Value
    properties:
      value: {map_merge: [{get_attr: [my_value, value]}, {get_param: param2}]}
      type: json
'''

    template_yaql = '''
heat_template_version: '2016-10-14'
parameters:
  param1:
    type: number
  param2:
    type: comma_delimited_list
resources:
  my_value:
    type: OS::Heat::Value
    properties:
      value: {get_param: param1}
      type: number
  my_value2:
    type: OS::Heat::Value
    properties:
      value:
        yaql:
          expression: $.data.param2.select(int($)).min()
          data:
            param2: {get_param: param2}
      type: number
  my_value3:
    type: OS::Heat::Value
    properties:
      value:
        yaql:
          expression: min($.data.v1,$.data.v2)
          data:
            v1: {get_attr: [my_value, value]}
            v2: {get_attr: [my_value2, value]}
'''

    def test_validation_fail(self):
        param1 = {"one": "croissant"}
        env = environment.Environment({
            'parameters': {'param1': json.dumps(param1)}})
        self.assertRaises(exception.StackValidationFailed,
                          self.create_stack, self.template_bad, env)

    def test_map(self):
        param1 = {"one": "skipper", "two": "antennae"}
        param2 = {"one": "monarch", "three": "sky"}
        env = environment.Environment({
            'parameters': {'param1': json.dumps(param1),
                           'param2': json.dumps(param2)}})
        stack = self.create_stack(self.template_map, env)
        my_value = stack['my_value']
        self.assertEqual(param1, my_value.FnGetAtt('value'))
        my_value2 = stack['my_value2']
        self.assertEqual({"one": "monarch",
                          "two": "antennae",
                          "three": "sky"}, my_value2.FnGetAtt('value'))

    def test_yaql(self):
        param1 = -800
        param2 = [-8, 0, 4, -11, 2]
        env = environment.Environment({
            'parameters': {'param1': param1, 'param2': param2}})
        stack = self.create_stack(self.template_yaql, env)
        my_value = stack['my_value']
        self.assertEqual(param1, my_value.FnGetAtt('value'))
        my_value2 = stack['my_value2']
        self.assertEqual(min(param2), my_value2.FnGetAtt('value'))
        my_value3 = stack['my_value3']
        self.assertEqual(param1, my_value3.FnGetAtt('value'))


class TestValueUpdate(TestValue):

    scenarios = [
        ('boolean-to-number', dict(
            param1=True, param_type1="boolean",
            param2=-100.999, param_type2="number")),
        ('number-to-string', dict(
            param1=-77, param_type1="number",
            param2='mellors', param_type2="string")),
        ('string-to-map', dict(
            param1='mellors', param_type1="string",
            param2={'3': 'turbo'}, param_type2="json")),
        ('map-to-boolean', dict(
            param1={'hey': 'there'}, param_type1="json",
            param2=False, param_type2="boolean")),
        ('list-to-boolean', dict(
            param1=['hey', '!'], param_type1="comma_delimited_list",
            param2=True, param_type2="boolean")),
    ]

    def test_value_update(self):
        ts1, tl1 = self.get_strict_and_loose_templates(self.param_type1)
        ts2, tl2 = self.get_strict_and_loose_templates(self.param_type2)

        env1 = environment.Environment({
            'parameters': {'param1': self.param1}})
        env2 = environment.Environment({
            'parameters': {'param1': self.param2}})

        updates = [(ts1, ts2), (ts1, tl2), (tl1, ts2), (tl1, tl2)]
        updates_other_way = [(b, a) for a, b in updates]
        updates.extend(updates_other_way)
        for t_initial, t_updated in updates:
            if t_initial == ts1 or t_initial == tl1:
                p1, p2, e1, e2 = self.param1, self.param2, env1, env2
            else:
                # starting with param2, updating to param1
                p2, p1, e2, e1 = self.param1, self.param2, env1, env2
            stack = self.create_stack(copy.deepcopy(t_initial), env=e1)
            self.assertEqual(p1, stack['my_value2'].FnGetAtt('value'))
            res1_id = stack['my_value'].id
            res2_id = stack['my_value2'].id
            res2_uuid = stack['my_value2'].uuid

            updated_stack = parser.Stack(
                stack.context, 'updated_stack',
                template.Template(copy.deepcopy(t_updated), env=e2))
            updated_stack.validate()
            stack.update(updated_stack)
            self.assertEqual(p2, stack['my_value2'].FnGetAtt('value'))
            # Make sure resources not replaced after update
            self.assertEqual(res1_id, stack['my_value'].id)
            self.assertEqual(res2_id, stack['my_value2'].id)
            self.assertEqual(res2_uuid, stack['my_value2'].uuid)
