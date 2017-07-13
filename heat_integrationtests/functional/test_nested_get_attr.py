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

# Using nested get_attr functions isn't a good idea - in particular, this
# actually working depends on correct dependencies between the two resources
# whose attributes are being fetched, and these dependencies are non-local to
# where the get_attr calls are used. Nevertheless, it did sort-of work, and
# this test will help keep it that way.

from heat_integrationtests.functional import functional_base


initial_template = '''
heat_template_version: ocata
resources:
  dict_resource:
    type: OS::Heat::Value
    properties:
      value:
        blarg: wibble
        foo: bar
        baz: quux
        fred: barney
    # These dependencies are required because we only want to read the
    # attribute values for a given resource once, and therefore we do so in
    # dependency order. This is necessarily true for a convergence traversal,
    # but also happens when we're fetching the resource attributes e.g. to show
    # the output values. The key1/key2 attribute values must be stored before
    # we attempt to calculate the dep_attrs for dict_resource in order to
    # correctly determine which attributes of dict_resource are used.
    depends_on:
      - key1
      - key2
      - indirect_key3_dep
  key1:
    type: OS::Heat::Value
    properties:
      value: blarg
  key2:
    type: OS::Heat::Value
    properties:
      value: foo
  key3:
    type: OS::Heat::Value
    properties:
      value: fred
  value1:
    type: OS::Heat::Value
    properties:
      value:
        get_attr:
          - dict_resource
          - value
          - {get_attr: [key1, value]}
  indirect_key3_dep:
    type: OS::Heat::Value
    properties:
      value: ignored
    depends_on: key3
outputs:
  value1:
    value: {get_attr: [value1, value]}
  value2:
    value: {get_attr: [dict_resource, value, {get_attr: [key2, value]}]}
  value3:
    value: {get_attr: [dict_resource, value, {get_attr: [key3, value]}]}
'''

update_template = '''
heat_template_version: ocata
resources:
  dict_resource:
    type: OS::Heat::Value
    properties:
      value:
        blarg: wibble
        foo: bar
        baz: quux
        fred: barney
    depends_on:
      - key1
      - key2
      - indirect_key3_dep
      - key4
  key1:
    type: OS::Heat::Value
    properties:
      value: foo
  key2:
    type: OS::Heat::Value
    properties:
      value: fred
  key3:
    type: OS::Heat::Value
    properties:
      value: blarg
  key4:
    type: OS::Heat::Value
    properties:
      value: baz
  value1:
    type: OS::Heat::Value
    properties:
      value:
        get_attr:
          - dict_resource
          - value
          - {get_attr: [key1, value]}
  value4:
    type: OS::Heat::Value
    properties:
      value:
        get_attr:
          - dict_resource
          - value
          - {get_attr: [key4, value]}
  indirect_key3_dep:
    type: OS::Heat::Value
    properties:
      value: ignored
    depends_on: key3
outputs:
  value1:
    value: {get_attr: [value1, value]}
  value2:
    value: {get_attr: [dict_resource, value, {get_attr: [key2, value]}]}
  value3:
    value: {get_attr: [dict_resource, value, {get_attr: [key3, value]}]}
  value4:
    value: {get_attr: [value4, value]}
'''


class NestedGetAttrTest(functional_base.FunctionalTestsBase):
    def assertOutput(self, value, stack_identifier, key):
        op = self.client.stacks.output_show(stack_identifier, key)['output']
        self.assertEqual(key, op['output_key'])
        if 'output_error' in op:
            raise Exception(op['output_error'])
        self.assertEqual(value, op['output_value'])

    def test_nested_get_attr_create(self):
        stack_identifier = self.stack_create(template=initial_template)

        self.assertOutput('wibble', stack_identifier, 'value1')
        self.assertOutput('bar', stack_identifier, 'value2')
        self.assertOutput('barney', stack_identifier, 'value3')

    def test_nested_get_attr_update(self):
        stack_identifier = self.stack_create(template=initial_template)
        self.update_stack(stack_identifier, template=update_template)

        self.assertOutput('bar', stack_identifier, 'value1')
        self.assertOutput('barney', stack_identifier, 'value2')
        self.assertOutput('wibble', stack_identifier, 'value3')
        self.assertOutput('quux', stack_identifier, 'value4')
