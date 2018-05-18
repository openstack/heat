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

from heatclient import exc
import six
import yaml

from heat_integrationtests.functional import functional_base


class ResourceGroupTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: 2013-05-23
resources:
  random_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: 0
      resource_def:
        type: My::RandomString
        properties:
          length: 30
          salt: initial
outputs:
  random1:
    value: {get_attr: [random_group, resource.0.value]}
  random2:
    value: {get_attr: [random_group, resource.1.value]}
  all_values:
    value: {get_attr: [random_group, value]}
'''

    def test_resource_group_zero_novalidate(self):
        # Nested resources should be validated only when size > 0
        # This allows features to be disabled via size=0 without
        # triggering validation of nested resource custom constraints
        # e.g images etc in the nested schema.
        nested_template_fail = '''
heat_template_version: 2013-05-23
parameters:
  length:
    type: string
    default: 50
  salt:
    type: string
    default: initial
resources:
  random:
    type: OS::Heat::RandomString
    properties:
      length: BAD
'''

        files = {'provider.yaml': nested_template_fail}
        env = {'resource_registry':
               {'My::RandomString': 'provider.yaml'}}
        stack_identifier = self.stack_create(
            template=self.template,
            files=files,
            environment=env
        )

        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))

        # Check we created an empty nested stack
        nested_identifier = self.group_nested_identifier(stack_identifier,
                                                         'random_group')
        self.assertEqual({}, self.list_resources(nested_identifier))

        # Prove validation works for non-zero create/update
        template_two_nested = self.template.replace("count: 0", "count: 2")
        expected_err = ("resources.random_group<nested_stack>.resources."
                        "0<provider.yaml>.resources.random: : "
                        "Value 'BAD' is not an integer")
        ex = self.assertRaises(exc.HTTPBadRequest, self.update_stack,
                               stack_identifier, template_two_nested,
                               environment=env, files=files)
        self.assertIn(expected_err, six.text_type(ex))

        ex = self.assertRaises(exc.HTTPBadRequest, self.stack_create,
                               template=template_two_nested,
                               environment=env, files=files)
        self.assertIn(expected_err, six.text_type(ex))

    def _validate_resources(self, stack_identifier, expected_count):
        resources = self.list_group_resources(stack_identifier,
                                              'random_group')
        self.assertEqual(expected_count, len(resources))
        expected_resources = dict(
            (str(idx), 'My::RandomString')
            for idx in range(expected_count))

        self.assertEqual(expected_resources, resources)

    def test_create(self):
        def validate_output(stack, output_key, length):
            output_value = self._stack_output(stack, output_key)
            self.assertEqual(length, len(output_value))
            return output_value
        # verify that the resources in resource group are identically
        # configured, resource names and outputs are appropriate.
        env = {'resource_registry':
               {'My::RandomString': 'OS::Heat::RandomString'}}
        create_template = self.template.replace("count: 0", "count: 2")
        stack_identifier = self.stack_create(template=create_template,
                                             environment=env)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))

        # validate count, type and name of resources in a resource group.
        self._validate_resources(stack_identifier, 2)

        # validate outputs
        stack = self.client.stacks.get(stack_identifier)
        outputs = []
        outputs.append(validate_output(stack, 'random1', 30))
        outputs.append(validate_output(stack, 'random2', 30))
        self.assertEqual(outputs, self._stack_output(stack, 'all_values'))

    def test_update_increase_decrease_count(self):
        # create stack with resource group count 2
        env = {'resource_registry':
               {'My::RandomString': 'OS::Heat::RandomString'}}
        create_template = self.template.replace("count: 0", "count: 2")
        stack_identifier = self.stack_create(template=create_template,
                                             environment=env)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))
        # verify that the resource group has 2 resources
        self._validate_resources(stack_identifier, 2)

        # increase the resource group count to 5
        update_template = self.template.replace("count: 0", "count: 5")
        self.update_stack(stack_identifier, update_template, environment=env)
        # verify that the resource group has 5 resources
        self._validate_resources(stack_identifier, 5)

        # decrease the resource group count to 3
        update_template = self.template.replace("count: 0", "count: 3")
        self.update_stack(stack_identifier, update_template, environment=env)
        # verify that the resource group has 3 resources
        self._validate_resources(stack_identifier, 3)

    def test_update_removal_policies(self):
        rp_template = '''
heat_template_version: 2014-10-16
resources:
  random_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: 5
      removal_policies: []
      resource_def:
        type: OS::Heat::RandomString
'''

        # create stack with resource group, initial count 5
        stack_identifier = self.stack_create(template=rp_template)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))
        group_resources = self.list_group_resources(stack_identifier,
                                                    'random_group')
        expected_resources = {u'0': u'OS::Heat::RandomString',
                              u'1': u'OS::Heat::RandomString',
                              u'2': u'OS::Heat::RandomString',
                              u'3': u'OS::Heat::RandomString',
                              u'4': u'OS::Heat::RandomString'}
        self.assertEqual(expected_resources, group_resources)

        # Remove three, specifying the middle resources to be removed
        update_template = rp_template.replace(
            'removal_policies: []',
            'removal_policies: [{resource_list: [\'1\', \'2\', \'3\']}]')
        self.update_stack(stack_identifier, update_template)
        group_resources = self.list_group_resources(stack_identifier,
                                                    'random_group')
        expected_resources = {u'0': u'OS::Heat::RandomString',
                              u'4': u'OS::Heat::RandomString',
                              u'5': u'OS::Heat::RandomString',
                              u'6': u'OS::Heat::RandomString',
                              u'7': u'OS::Heat::RandomString'}
        self.assertEqual(expected_resources, group_resources)

    def test_props_update(self):
        """Test update of resource_def properties behaves as expected."""

        env = {'resource_registry':
               {'My::RandomString': 'OS::Heat::RandomString'}}
        template_one = self.template.replace("count: 0", "count: 1")
        stack_identifier = self.stack_create(template=template_one,
                                             environment=env)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))

        initial_nested_ident = self.group_nested_identifier(stack_identifier,
                                                            'random_group')
        self.assertEqual({'0': 'My::RandomString'},
                         self.list_resources(initial_nested_ident))
        # get the resource id
        res = self.client.resources.get(initial_nested_ident, '0')
        initial_res_id = res.physical_resource_id

        # change the salt (this should replace the RandomString but
        # not the nested stack or resource group.
        template_salt = template_one.replace("salt: initial", "salt: more")
        self.update_stack(stack_identifier, template_salt, environment=env)
        updated_nested_ident = self.group_nested_identifier(stack_identifier,
                                                            'random_group')
        self.assertEqual(initial_nested_ident, updated_nested_ident)

        # compare the resource id, we expect a change.
        res = self.client.resources.get(updated_nested_ident, '0')
        updated_res_id = res.physical_resource_id
        self.assertNotEqual(initial_res_id, updated_res_id)

    def test_update_nochange(self):
        """Test update with no properties change."""

        env = {'resource_registry':
               {'My::RandomString': 'OS::Heat::RandomString'}}
        template_one = self.template.replace("count: 0", "count: 2")
        stack_identifier = self.stack_create(template=template_one,
                                             environment=env)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))

        initial_nested_ident = self.group_nested_identifier(stack_identifier,
                                                            'random_group')
        self.assertEqual({'0': 'My::RandomString', '1': 'My::RandomString'},
                         self.list_resources(initial_nested_ident))
        # get the output
        stack0 = self.client.stacks.get(stack_identifier)
        initial_rand = self._stack_output(stack0, 'random1')

        template_copy = copy.deepcopy(template_one)
        self.update_stack(stack_identifier, template_copy, environment=env)
        updated_nested_ident = self.group_nested_identifier(stack_identifier,
                                                            'random_group')
        self.assertEqual(initial_nested_ident, updated_nested_ident)

        # compare the random number, we expect no change.
        stack1 = self.client.stacks.get(stack_identifier)
        updated_rand = self._stack_output(stack1, 'random1')
        self.assertEqual(initial_rand, updated_rand)

    def test_update_nochange_resource_needs_update(self):
        """Test update when the resource definition has changed.

        Test the scenario when the ResourceGroup update happens without
        any changed properties, this can happen if the definition of
        a contained provider resource changes (files map changes), then
        the group and underlying nested stack should end up updated.
        """

        random_templ1 = '''
heat_template_version: 2013-05-23
parameters:
  length:
    type: string
    default: not-used
  salt:
    type: string
    default: not-used
resources:
  random1:
    type: OS::Heat::RandomString
    properties:
      salt: initial
outputs:
  value:
    value: {get_attr: [random1, value]}
'''
        files1 = {'my_random.yaml': random_templ1}

        random_templ2 = random_templ1.replace('salt: initial',
                                              'salt: more')
        files2 = {'my_random.yaml': random_templ2}

        env = {'resource_registry':
               {'My::RandomString': 'my_random.yaml'}}

        template_one = self.template.replace("count: 0", "count: 2")
        stack_identifier = self.stack_create(template=template_one,
                                             environment=env,
                                             files=files1)
        self.assertEqual({u'random_group': u'OS::Heat::ResourceGroup'},
                         self.list_resources(stack_identifier))
        self.assertEqual(files1, self.client.stacks.files(stack_identifier))

        initial_nested_ident = self.group_nested_identifier(stack_identifier,
                                                            'random_group')
        self.assertEqual({'0': 'My::RandomString', '1': 'My::RandomString'},
                         self.list_resources(initial_nested_ident))
        # get the output
        stack0 = self.client.stacks.get(stack_identifier)
        initial_rand = self._stack_output(stack0, 'random1')

        # change the environment so we use a different TemplateResource.
        # note "files2".
        self.update_stack(stack_identifier, template_one,
                          environment=env, files=files2)
        updated_nested_ident = self.group_nested_identifier(stack_identifier,
                                                            'random_group')
        self.assertEqual(initial_nested_ident, updated_nested_ident)
        self.assertEqual(files2, self.client.stacks.files(stack_identifier))

        # compare the output, we expect a change.
        stack1 = self.client.stacks.get(stack_identifier)
        updated_rand = self._stack_output(stack1, 'random1')
        self.assertNotEqual(initial_rand, updated_rand)

    def test_validation(self):
        resource_group = '''
heat_template_version: 2016-10-14

parameters:
  the_count:
    type: number

resources:

  the_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: {get_param: the_count}
      resource_def:
        type: OS::Heat::RandomString
'''
        ret = self.client.stacks.validate(template=resource_group)
        expected = {'Description': 'No description',
                    'Environment': {'event_sinks': [],
                                    'parameter_defaults': {},
                                    'parameters': {},
                                    'resource_registry': {u'resources': {}}},
                    'Parameters': {
                        'the_count': {'Description': '',
                                      'Label': 'the_count',
                                      'NoEcho': 'false',
                                      'Type': 'Number'}}}

        self.assertEqual(expected, ret)


class ResourceGroupTestNullParams(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: 2013-05-23
parameters:
  param:
    type: empty
resources:
  random_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: 1
      resource_def:
        type: My::RandomString
        properties:
          param: {get_param: param}
outputs:
  val:
    value: {get_attr: [random_group, val]}
'''

    nested_template_file = '''
heat_template_version: 2013-05-23
parameters:
  param:
    type: empty
outputs:
  val:
    value: {get_param: param}
'''

    scenarios = [
        ('string_empty', dict(
            param='',
            p_type='string',
        )),
        ('boolean_false', dict(
            param=False,
            p_type='boolean',
        )),
        ('number_zero', dict(
            param=0,
            p_type='number',
        )),
        ('comma_delimited_list', dict(
            param=[],
            p_type='comma_delimited_list',
        )),
        ('json_empty', dict(
            param={},
            p_type='json',
        )),
    ]

    def test_create_pass_zero_parameter(self):
        templ = self.template.replace('type: empty',
                                      'type: %s' % self.p_type)
        n_t_f = self.nested_template_file.replace('type: empty',
                                                  'type: %s' % self.p_type)
        files = {'provider.yaml': n_t_f}
        env = {'resource_registry':
               {'My::RandomString': 'provider.yaml'}}
        stack_identifier = self.stack_create(
            template=templ,
            files=files,
            environment=env,
            parameters={'param': self.param}
        )
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual(self.param, self._stack_output(stack, 'val')[0])


class ResourceGroupAdoptTest(functional_base.FunctionalTestsBase):
    """Prove that we can do resource group adopt."""

    main_template = '''
heat_template_version: "2013-05-23"
resources:
  group1:
    type: OS::Heat::ResourceGroup
    properties:
      count: 2
      resource_def:
        type: OS::Heat::RandomString
outputs:
  test0:
    value: {get_attr: [group1, resource.0.value]}
  test1:
    value: {get_attr: [group1, resource.1.value]}
'''

    def _yaml_to_json(self, yaml_templ):
        return yaml.safe_load(yaml_templ)

    def test_adopt(self):
        data = {
            "resources": {
                "group1": {
                    "status": "COMPLETE",
                    "name": "group1",
                    "resource_data": {},
                    "metadata": {},
                    "resource_id": "test-group1-id",
                    "action": "CREATE",
                    "type": "OS::Heat::ResourceGroup",
                    "resources": {
                        "0": {
                            "status": "COMPLETE",
                            "name": "0",
                            "resource_data": {"value": "goopie"},
                            "resource_id": "ID-0",
                            "action": "CREATE",
                            "type": "OS::Heat::RandomString",
                            "metadata": {}
                        },
                        "1": {
                            "status": "COMPLETE",
                            "name": "1",
                            "resource_data": {"value": "different"},
                            "resource_id": "ID-1",
                            "action": "CREATE",
                            "type": "OS::Heat::RandomString",
                            "metadata": {}
                        }
                    }
                }
            },
            "environment": {"parameters": {}},
            "template": yaml.safe_load(self.main_template)
        }
        stack_identifier = self.stack_adopt(
            adopt_data=json.dumps(data))

        self.assert_resource_is_a_stack(stack_identifier, 'group1')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('goopie', self._stack_output(stack, 'test0'))
        self.assertEqual('different', self._stack_output(stack, 'test1'))


class ResourceGroupErrorResourceTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: "2013-05-23"
resources:
  group1:
    type: OS::Heat::ResourceGroup
    properties:
      count: 2
      resource_def:
        type: fail.yaml
'''
    nested_templ = '''
heat_template_version: "2013-05-23"
resources:
  oops:
    type: OS::Heat::TestResource
    properties:
      fail: true
      wait_secs: 2
'''

    def test_fail(self):
        stack_identifier = self.stack_create(
            template=self.template,
            files={'fail.yaml': self.nested_templ},
            expected_status='CREATE_FAILED',
            enable_cleanup=False)
        stack = self.client.stacks.get(stack_identifier)

        self.assertEqual('CREATE_FAILED', stack.stack_status)
        self.client.stacks.delete(stack_identifier)
        self._wait_for_stack_status(
            stack_identifier, 'DELETE_COMPLETE',
            success_on_not_found=True)


class ResourceGroupUpdatePolicyTest(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: '2015-04-30'
resources:
  random_group:
    type: OS::Heat::ResourceGroup
    update_policy:
      rolling_update:
        min_in_service: 1
        max_batch_size: 2
        pause_time: 1
    properties:
      count: 10
      resource_def:
        type: OS::Heat::TestResource
        properties:
          value: initial
          update_replace: False
'''

    def update_resource_group(self, update_template,
                              updated, created, deleted):
        stack_identifier = self.stack_create(template=self.template)
        group_resources = self.list_group_resources(stack_identifier,
                                                    'random_group',
                                                    minimal=False)

        init_names = [res.physical_resource_id for res in group_resources]

        self.update_stack(stack_identifier, update_template)
        group_resources = self.list_group_resources(stack_identifier,
                                                    'random_group',
                                                    minimal=False)

        updt_names = [res.physical_resource_id for res in group_resources]

        matched_names = set(updt_names) & set(init_names)

        self.assertEqual(updated, len(matched_names))

        self.assertEqual(created, len(set(updt_names) - set(init_names)))

        self.assertEqual(deleted, len(set(init_names) - set(updt_names)))

    def test_resource_group_update(self):
        """Test rolling update with no conflict.

        Simple rolling update with no conflict in batch size
        and minimum instances in service.
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '1'
        policy['max_batch_size'] = '3'
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'

        self.update_resource_group(updt_template,
                                   updated=10,
                                   created=0,
                                   deleted=0)

    def test_resource_group_update_replace(self):
        """Test rolling update(replace)with no conflict.

        Simple rolling update replace with no conflict in batch size
        and minimum instances in service.
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '1'
        policy['max_batch_size'] = '3'
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'
        res_def['properties']['update_replace'] = True

        self.update_resource_group(updt_template,
                                   updated=0,
                                   created=10,
                                   deleted=10)

    def test_resource_group_update_replace_template_changed(self):
        """Test rolling update(replace)with child template path changed.

        Simple rolling update replace with child template path changed.
        """

        nested_templ = '''
heat_template_version: "2013-05-23"
resources:
  oops:
    type: OS::Heat::TestResource
'''

        create_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = create_template['resources']['random_group']
        grp['properties']['resource_def'] = {'type': '/opt/provider.yaml'}
        files = {'/opt/provider.yaml': nested_templ}

        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '1'
        policy['max_batch_size'] = '3'
        stack_identifier = self.stack_create(template=create_template,
                                             files=files)
        update_template = create_template.copy()
        grp = update_template['resources']['random_group']
        grp['properties']['resource_def'] = {'type': '/opt1/provider.yaml'}
        files = {'/opt1/provider.yaml': nested_templ}

        self.update_stack(stack_identifier, update_template, files=files)

    def test_resource_group_update_scaledown(self):
        """Test rolling update with scaledown.

        Simple rolling update with reduced size.
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '1'
        policy['max_batch_size'] = '3'
        grp['properties']['count'] = 6
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'

        self.update_resource_group(updt_template,
                                   updated=6,
                                   created=0,
                                   deleted=4)

    def test_resource_group_update_scaleup(self):
        """Test rolling update with scaleup.

        Simple rolling update with increased size.
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '1'
        policy['max_batch_size'] = '3'
        grp['properties']['count'] = 12
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'

        self.update_resource_group(updt_template,
                                   updated=10,
                                   created=2,
                                   deleted=0)

    def test_resource_group_update_adjusted(self):
        """Test rolling update with enough available resources

        Update  with capacity adjustment with enough resources.
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '8'
        policy['max_batch_size'] = '4'
        grp['properties']['count'] = 6
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'

        self.update_resource_group(updt_template,
                                   updated=6,
                                   created=0,
                                   deleted=4)

    def test_resource_group_update_with_adjusted_capacity(self):
        """Test rolling update with capacity adjustment.

        Rolling update with capacity adjustment due to conflict in
        batch size and minimum instances in service.
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '8'
        policy['max_batch_size'] = '4'
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'

        self.update_resource_group(updt_template,
                                   updated=10,
                                   created=0,
                                   deleted=0)

    def test_resource_group_update_huge_batch_size(self):
        """Test rolling update with huge batch size.

        Rolling Update with a huge batch size(more than
        current size).
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '0'
        policy['max_batch_size'] = '20'
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'
        self.update_resource_group(updt_template,
                                   updated=10,
                                   created=0,
                                   deleted=0)

    def test_resource_group_update_huge_min_in_service(self):
        """Test rolling update with huge minimum capacity.

        Rolling Update with a huge number of minimum instances
        in service.
        """
        updt_template = yaml.safe_load(copy.deepcopy(self.template))
        grp = updt_template['resources']['random_group']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '20'
        policy['max_batch_size'] = '1'
        res_def = grp['properties']['resource_def']
        res_def['properties']['value'] = 'updated'

        self.update_resource_group(updt_template,
                                   updated=10,
                                   created=0,
                                   deleted=0)
