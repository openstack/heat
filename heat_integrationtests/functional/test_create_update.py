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

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base

test_template_one_resource = {
    'heat_template_version': 'pike',
    'description': 'Test template to create one instance.',
    'resources': {
        'test1': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                'fail': False,
                'update_replace': False,
                'wait_secs': 1,
                'action_wait_secs': {'create': 1},
                'client_name': 'nova',
                'entity_name': 'servers',
            }
        }
    }
}

test_template_two_resource = {
    'heat_template_version': 'pike',
    'description': 'Test template to create two instance.',
    'resources': {
        'test1': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                'fail': False,
                'update_replace': False,
                'wait_secs': 0,
                'action_wait_secs': {'update': 1}
            }
        },
        'test2': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                'fail': False,
                'update_replace': False,
                'wait_secs': 0
            }
        }
    }
}


def _change_rsrc_properties(template, rsrcs, values):
        modified_template = copy.deepcopy(template)
        for rsrc_name in rsrcs:
            rsrc_prop = modified_template['resources'][
                rsrc_name]['properties']
            for prop, new_val in values.items():
                rsrc_prop[prop] = new_val
        return modified_template


class CreateStackTest(functional_base.FunctionalTestsBase):
    def test_create_rollback(self):
        values = {'fail': True, 'value': 'test_create_rollback'}
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'], values)

        self.stack_create(
            template=template,
            expected_status='ROLLBACK_COMPLETE',
            disable_rollback=False)


class UpdateStackTest(functional_base.FunctionalTestsBase):

    provider_template = {
        'heat_template_version': '2013-05-23',
        'description': 'foo',
        'resources': {
            'test1': {
                'type': 'My::TestResource'
            }
        }
    }

    provider_group_template = '''
heat_template_version: 2013-05-23
parameters:
  count:
    type: number
    default: 2
resources:
  test_group:
    type: OS::Heat::ResourceGroup
    properties:
      count: {get_param: count}
      resource_def:
        type: My::TestResource
'''

    update_userdata_template = '''
heat_template_version: 2014-10-16
parameters:
  flavor:
    type: string
  user_data:
    type: string
  image:
    type: string
  network:
    type: string

resources:
  server:
    type: OS::Nova::Server
    properties:
      image: {get_param: image}
      flavor: {get_param: flavor}
      networks: [{network: {get_param: network} }]
      user_data_format: SOFTWARE_CONFIG
      user_data: {get_param: user_data}
'''

    fail_param_template = '''
heat_template_version: 2014-10-16
parameters:
  do_fail:
    type: boolean
    default: False
resources:
  aresource:
    type: OS::Heat::TestResource
    properties:
      value: Test
      fail: {get_param: do_fail}
      wait_secs: 1
'''

    def test_stack_update_nochange(self):
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'],
                                           {'value': 'test_no_change'})
        stack_identifier = self.stack_create(
            template=template)
        expected_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))

        # Update with no changes, resources should be unchanged
        self.update_stack(stack_identifier, template)
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))

    def test_stack_in_place_update(self):
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'],
                                           {'value': 'test_in_place'})
        stack_identifier = self.stack_create(
            template=template)
        expected_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))
        resource = self.client.resources.list(stack_identifier)
        initial_phy_id = resource[0].physical_resource_id

        tmpl_update = _change_rsrc_properties(
            test_template_one_resource, ['test1'],
            {'value': 'test_in_place_update'})
        # Update the Value
        self.update_stack(stack_identifier, tmpl_update)
        resource = self.client.resources.list(stack_identifier)
        # By default update_in_place
        self.assertEqual(initial_phy_id,
                         resource[0].physical_resource_id)

    def test_stack_update_replace(self):
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'],
                                           {'value': 'test_replace'})
        stack_identifier = self.stack_create(
            template=template)
        expected_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(expected_resources,
                         self.list_resources(stack_identifier))
        resource = self.client.resources.list(stack_identifier)
        initial_phy_id = resource[0].physical_resource_id

        # Update the value and also set update_replace prop
        tmpl_update = _change_rsrc_properties(
            test_template_one_resource, ['test1'],
            {'value': 'test_in_place_update', 'update_replace': True})
        self.update_stack(stack_identifier, tmpl_update)
        resource = self.client.resources.list(stack_identifier)
        # update Replace
        self.assertNotEqual(initial_phy_id,
                            resource[0].physical_resource_id)

    def test_stack_update_add_remove(self):
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'],
                                           {'value': 'test_add_remove'})
        stack_identifier = self.stack_create(
            template=template)
        initial_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        tmpl_update = _change_rsrc_properties(
            test_template_two_resource, ['test1', 'test2'],
            {'value': 'test_add_remove_update'})
        # Add one resource via a stack update
        self.update_stack(stack_identifier, tmpl_update)
        updated_resources = {'test1': 'OS::Heat::TestResource',
                             'test2': 'OS::Heat::TestResource'}
        self.assertEqual(updated_resources,
                         self.list_resources(stack_identifier))

        # Then remove it by updating with the original template
        self.update_stack(stack_identifier, template)
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

    def test_stack_update_rollback(self):
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'],
                                           {'value': 'test_update_rollback'})
        stack_identifier = self.stack_create(
            template=template)
        initial_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        tmpl_update = _change_rsrc_properties(
            test_template_two_resource, ['test1', 'test2'],
            {'value': 'test_update_rollback', 'fail': True})
        # stack update, also set failure
        self.update_stack(stack_identifier, tmpl_update,
                          expected_status='ROLLBACK_COMPLETE',
                          disable_rollback=False)
        # since stack update failed only the original resource is present
        updated_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(updated_resources,
                         self.list_resources(stack_identifier))

    def test_stack_update_from_failed(self):
        # Prove it's possible to update from an UPDATE_FAILED state
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'],
                                           {'value': 'test_update_failed'})
        stack_identifier = self.stack_create(
            template=template)
        initial_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        tmpl_update = _change_rsrc_properties(
            test_template_one_resource, ['test1'], {'fail': True})
        # Update with bad template, we should fail
        self.update_stack(stack_identifier, tmpl_update,
                          expected_status='UPDATE_FAILED')
        # but then passing a good template should succeed
        self.update_stack(stack_identifier, test_template_two_resource)
        updated_resources = {'test1': 'OS::Heat::TestResource',
                             'test2': 'OS::Heat::TestResource'}
        self.assertEqual(updated_resources,
                         self.list_resources(stack_identifier))

    @test.requires_convergence
    def test_stack_update_replace_manual_rollback(self):
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'],
                                           {'update_replace_value': '1'})
        stack_identifier = self.stack_create(template=template)
        original_resource_id = self.get_physical_resource_id(stack_identifier,
                                                             'test1')

        tmpl_update = _change_rsrc_properties(test_template_one_resource,
                                              ['test1'],
                                              {'update_replace_value': '2',
                                               'fail': True})
        # Update with bad template, we should fail
        self.update_stack(stack_identifier, tmpl_update,
                          expected_status='UPDATE_FAILED',
                          disable_rollback=True)
        # Manually roll back to previous template
        self.update_stack(stack_identifier, template)
        final_resource_id = self.get_physical_resource_id(stack_identifier,
                                                          'test1')
        # Original resource was good, and replacement was never created, so it
        # should be kept.
        self.assertEqual(original_resource_id, final_resource_id)

    def test_stack_update_provider(self):
        template = _change_rsrc_properties(
            test_template_one_resource, ['test1'],
            {'value': 'test_provider_template'})
        files = {'provider.template': json.dumps(template)}
        env = {'resource_registry':
               {'My::TestResource': 'provider.template'}}
        stack_identifier = self.stack_create(
            template=self.provider_template,
            files=files,
            environment=env
        )

        initial_resources = {'test1': 'My::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Prove the resource is backed by a nested stack, save the ID
        nested_identifier = self.assert_resource_is_a_stack(stack_identifier,
                                                            'test1')
        nested_id = nested_identifier.split('/')[-1]

        # Then check the expected resources are in the nested stack
        nested_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))
        tmpl_update = _change_rsrc_properties(
            test_template_two_resource, ['test1', 'test2'],
            {'value': 'test_provider_template'})
        # Add one resource via a stack update by changing the nested stack
        files['provider.template'] = json.dumps(tmpl_update)
        self.update_stack(stack_identifier, self.provider_template,
                          environment=env, files=files)

        # Parent resources should be unchanged and the nested stack
        # should have been updated in-place without replacement
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))
        rsrc = self.client.resources.get(stack_identifier, 'test1')
        self.assertEqual(rsrc.physical_resource_id, nested_id)

        # Then check the expected resources are in the nested stack
        nested_resources = {'test1': 'OS::Heat::TestResource',
                            'test2': 'OS::Heat::TestResource'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

    def test_stack_update_alias_type(self):
        env = {'resource_registry':
               {'My::TestResource': 'OS::Heat::RandomString',
                'My::TestResource2': 'OS::Heat::RandomString'}}
        stack_identifier = self.stack_create(
            template=self.provider_template,
            environment=env
        )
        p_res = self.client.resources.get(stack_identifier, 'test1')
        self.assertEqual('My::TestResource', p_res.resource_type)

        initial_resources = {'test1': 'My::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))
        res = self.client.resources.get(stack_identifier, 'test1')
        # Modify the type of the resource alias to My::TestResource2
        tmpl_update = copy.deepcopy(self.provider_template)
        tmpl_update['resources']['test1']['type'] = 'My::TestResource2'
        self.update_stack(stack_identifier, tmpl_update, environment=env)
        res_a = self.client.resources.get(stack_identifier, 'test1')
        self.assertEqual(res.physical_resource_id, res_a.physical_resource_id)
        self.assertEqual(res.attributes['value'], res_a.attributes['value'])

    def test_stack_update_alias_changes(self):
        env = {'resource_registry':
               {'My::TestResource': 'OS::Heat::RandomString'}}
        stack_identifier = self.stack_create(
            template=self.provider_template,
            environment=env
        )
        p_res = self.client.resources.get(stack_identifier, 'test1')
        self.assertEqual('My::TestResource', p_res.resource_type)

        initial_resources = {'test1': 'My::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))
        res = self.client.resources.get(stack_identifier, 'test1')
        # Modify the resource alias to point to a different type
        env = {'resource_registry':
               {'My::TestResource': 'OS::Heat::TestResource'}}
        self.update_stack(stack_identifier, template=self.provider_template,
                          environment=env)
        res_a = self.client.resources.get(stack_identifier, 'test1')
        self.assertNotEqual(res.physical_resource_id,
                            res_a.physical_resource_id)

    def test_stack_update_provider_type(self):
        template = _change_rsrc_properties(
            test_template_one_resource, ['test1'],
            {'value': 'test_provider_template'})
        files = {'provider.template': json.dumps(template)}
        env = {'resource_registry':
               {'My::TestResource': 'provider.template',
                'My::TestResource2': 'provider.template'}}
        stack_identifier = self.stack_create(
            template=self.provider_template,
            files=files,
            environment=env
        )
        p_res = self.client.resources.get(stack_identifier, 'test1')
        self.assertEqual('My::TestResource', p_res.resource_type)

        initial_resources = {'test1': 'My::TestResource'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Prove the resource is backed by a nested stack, save the ID
        nested_identifier = self.assert_resource_is_a_stack(stack_identifier,
                                                            'test1')
        nested_id = nested_identifier.split('/')[-1]

        # Then check the expected resources are in the nested stack
        nested_resources = {'test1': 'OS::Heat::TestResource'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))
        n_res = self.client.resources.get(nested_identifier, 'test1')

        # Modify the type of the provider resource to My::TestResource2
        tmpl_update = copy.deepcopy(self.provider_template)
        tmpl_update['resources']['test1']['type'] = 'My::TestResource2'
        self.update_stack(stack_identifier, tmpl_update,
                          environment=env, files=files)
        p_res = self.client.resources.get(stack_identifier, 'test1')
        self.assertEqual('My::TestResource2', p_res.resource_type)

        # Parent resources should be unchanged and the nested stack
        # should have been updated in-place without replacement
        self.assertEqual({u'test1': u'My::TestResource2'},
                         self.list_resources(stack_identifier))
        rsrc = self.client.resources.get(stack_identifier, 'test1')
        self.assertEqual(rsrc.physical_resource_id, nested_id)

        # Then check the expected resources are in the nested stack
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))
        n_res2 = self.client.resources.get(nested_identifier, 'test1')
        self.assertEqual(n_res.physical_resource_id,
                         n_res2.physical_resource_id)

    def test_stack_update_provider_group(self):
        """Test two-level nested update."""

        # Create a ResourceGroup (which creates a nested stack),
        # containing provider resources (which create a nested
        # stack), thus exercising an update which traverses
        # two levels of nesting.
        template = _change_rsrc_properties(
            test_template_one_resource, ['test1'],
            {'value': 'test_provider_group_template'})
        files = {'provider.template': json.dumps(template)}
        env = {'resource_registry':
               {'My::TestResource': 'provider.template'}}

        stack_identifier = self.stack_create(
            template=self.provider_group_template,
            files=files,
            environment=env
        )

        initial_resources = {'test_group': 'OS::Heat::ResourceGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Prove the resource is backed by a nested stack, save the ID
        nested_identifier = self.assert_resource_is_a_stack(stack_identifier,
                                                            'test_group')

        # Then check the expected resources are in the nested stack
        nested_resources = {'0': 'My::TestResource',
                            '1': 'My::TestResource'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

        for n_rsrc in nested_resources:
            rsrc = self.client.resources.get(nested_identifier, n_rsrc)
            provider_stack = self.client.stacks.get(rsrc.physical_resource_id)
            provider_identifier = '%s/%s' % (provider_stack.stack_name,
                                             provider_stack.id)
            provider_resources = {u'test1': u'OS::Heat::TestResource'}
            self.assertEqual(provider_resources,
                             self.list_resources(provider_identifier))

        tmpl_update = _change_rsrc_properties(
            test_template_two_resource, ['test1', 'test2'],
            {'value': 'test_provider_group_template'})
        # Add one resource via a stack update by changing the nested stack
        files['provider.template'] = json.dumps(tmpl_update)
        self.update_stack(stack_identifier, self.provider_group_template,
                          environment=env, files=files)

        # Parent resources should be unchanged and the nested stack
        # should have been updated in-place without replacement
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Resource group stack should also be unchanged (but updated)
        nested_stack = self.client.stacks.get(nested_identifier)
        self.assertEqual('UPDATE_COMPLETE', nested_stack.stack_status)
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

        for n_rsrc in nested_resources:
            rsrc = self.client.resources.get(nested_identifier, n_rsrc)
            provider_stack = self.client.stacks.get(rsrc.physical_resource_id)
            provider_identifier = '%s/%s' % (provider_stack.stack_name,
                                             provider_stack.id)
            provider_resources = {'test1': 'OS::Heat::TestResource',
                                  'test2': 'OS::Heat::TestResource'}
            self.assertEqual(provider_resources,
                             self.list_resources(provider_identifier))

    def test_stack_update_with_replacing_userdata(self):
        """Test case for updating userdata of instance.

        Confirm that we can update userdata of instance during updating stack
        by the user of member role.

        Make sure that a resource that inherits from StackUser can be deleted
        during updating stack.
        """
        if not self.conf.minimal_image_ref:
            raise self.skipException("No minimal image configured to test")
        if not self.conf.minimal_instance_type:
            raise self.skipException("No flavor configured to test")

        parms = {'flavor': self.conf.minimal_instance_type,
                 'image': self.conf.minimal_image_ref,
                 'network': self.conf.fixed_network_name,
                 'user_data': ''}

        stack_identifier = self.stack_create(
            template=self.update_userdata_template,
            parameters=parms
        )

        parms_updated = parms
        parms_updated['user_data'] = 'two'
        self.update_stack(
            stack_identifier,
            template=self.update_userdata_template,
            parameters=parms_updated)

    def test_stack_update_provider_group_patch(self):
        '''Test two-level nested update with PATCH'''
        template = _change_rsrc_properties(
            test_template_one_resource, ['test1'],
            {'value': 'test_provider_group_template'})
        files = {'provider.template': json.dumps(template)}
        env = {'resource_registry':
               {'My::TestResource': 'provider.template'}}

        stack_identifier = self.stack_create(
            template=self.provider_group_template,
            files=files,
            environment=env
        )

        initial_resources = {'test_group': 'OS::Heat::ResourceGroup'}
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Prove the resource is backed by a nested stack, save the ID
        nested_identifier = self.assert_resource_is_a_stack(stack_identifier,
                                                            'test_group')

        # Then check the expected resources are in the nested stack
        nested_resources = {'0': 'My::TestResource',
                            '1': 'My::TestResource'}
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

        # increase the count, pass only the paramter, no env or template
        params = {'count': 3}
        self.update_stack(stack_identifier, parameters=params, existing=True)

        # Parent resources should be unchanged and the nested stack
        # should have been updated in-place without replacement
        self.assertEqual(initial_resources,
                         self.list_resources(stack_identifier))

        # Resource group stack should also be unchanged (but updated)
        nested_stack = self.client.stacks.get(nested_identifier)
        self.assertEqual('UPDATE_COMPLETE', nested_stack.stack_status)
        # Add a resource, as we should have added one
        nested_resources['2'] = 'My::TestResource'
        self.assertEqual(nested_resources,
                         self.list_resources(nested_identifier))

    def test_stack_update_from_failed_patch(self):
        '''Test PATCH update from a failed state.'''

        # Start with empty template
        stack_identifier = self.stack_create(
            template='heat_template_version: 2014-10-16')

        # Update with a good template, but bad parameter
        self.update_stack(stack_identifier,
                          template=self.fail_param_template,
                          parameters={'do_fail': True},
                          expected_status='UPDATE_FAILED')

        # PATCH update, only providing the parameter
        self.update_stack(stack_identifier,
                          parameters={'do_fail': False},
                          existing=True)
        self.assertEqual({u'aresource': u'OS::Heat::TestResource'},
                         self.list_resources(stack_identifier))

    def test_stack_update_with_new_env(self):
        """Update handles new resource types in the environment.

        If a resource type appears during an update and the update fails,
        retrying the update is able to find the type properly in the
        environment.
        """
        stack_identifier = self.stack_create(
            template=test_template_one_resource)

        # Update with a new resource and make the update fails
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'], {'fail': True})
        template['resources']['test2'] = {'type': 'My::TestResource'}
        template['resources']['test1']['depends_on'] = 'test2'
        env = {'resource_registry':
               {'My::TestResource': 'OS::Heat::TestResource'}}
        self.update_stack(stack_identifier,
                          template=template,
                          environment=env,
                          expected_status='UPDATE_FAILED')

        # Fixing the template should fix the stack
        template = _change_rsrc_properties(template,
                                           ['test1'], {'fail': False})
        template['resources']['test2'][
            'properties'] = {'action_wait_secs': {'update': 1}}
        self.update_stack(stack_identifier,
                          template=template,
                          environment=env)
        self.assertEqual({'test1': 'OS::Heat::TestResource',
                          'test2': 'My::TestResource'},
                         self.list_resources(stack_identifier))

    def test_stack_update_with_new_version(self):
        """Update handles new template version in failure.

        If a stack update fails while changing the template version, update is
        able to handle the new version fine.
        """
        stack_identifier = self.stack_create(
            template=test_template_one_resource)

        # Update with a new function and make the update fails
        template = _change_rsrc_properties(test_template_two_resource,
                                           ['test1'], {'fail': True})

        template['heat_template_version'] = '2015-10-15'
        template['resources']['test2']['properties']['value'] = {
            'list_join': [',', ['a'], ['b']]}
        self.update_stack(stack_identifier,
                          template=template,
                          expected_status='UPDATE_FAILED')

        template = _change_rsrc_properties(template,
                                           ['test2'], {'value': 'Test2'})
        template['resources']['test1'][
            'properties']['action_wait_secs'] = {'create': 1}
        self.update_stack(stack_identifier,
                          template=template,
                          expected_status='UPDATE_FAILED')
        self._stack_delete(stack_identifier)

    def test_stack_update_with_old_version(self):
        """Update handles old template version in failure.

        If a stack update fails while changing the template version, update is
        able to handle the old version fine.
        """
        template = _change_rsrc_properties(
            test_template_one_resource,
            ['test1'], {'value': {'list_join': [',', ['a'], ['b']]}})
        template['heat_template_version'] = '2015-10-15'
        stack_identifier = self.stack_create(
            template=template)

        # Update with a new function and make the update fails
        template = _change_rsrc_properties(test_template_one_resource,
                                           ['test1'], {'fail': True})
        self.update_stack(stack_identifier,
                          template=template,
                          expected_status='UPDATE_FAILED')
        self._stack_delete(stack_identifier)

    def _test_conditional(self, test3_resource):
        """Update manages new conditions added.

        When a new resource is added during updates, the stacks handles the new
        conditions correctly, and doesn't fail to load them while the update is
        still in progress.
        """
        stack_identifier = self.stack_create(
            template=test_template_one_resource)

        updated_template = copy.deepcopy(test_template_two_resource)
        updated_template['conditions'] = {'cond1': True}
        updated_template['resources']['test3'] = test3_resource
        test2_props = updated_template['resources']['test2']['properties']
        test2_props['action_wait_secs'] = {'create': 30}

        self.update_stack(stack_identifier,
                          template=updated_template,
                          expected_status='UPDATE_IN_PROGRESS')

        def check_resources():
            def is_complete(r):
                return r.resource_status in {'CREATE_COMPLETE',
                                             'UPDATE_COMPLETE'}

            resources = self.list_resources(stack_identifier, is_complete)
            if len(resources) < 2:
                return False
            self.assertIn('test3', resources)
            return True

        self.assertTrue(test.call_until_true(20, 2, check_resources))

    def test_stack_update_with_if_conditions(self):
        test3 = {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': {'if': ['cond1', 'val3', 'val4']}
            }
        }
        self._test_conditional(test3)

    def test_stack_update_with_conditions(self):
        test3 = {
            'type': 'OS::Heat::TestResource',
            'condition': 'cond1',
            'properties': {
                'value': 'foo',
            }
        }
        self._test_conditional(test3)

    def test_inplace_update_old_ref_deleted_failed_stack(self):
        template = '''
heat_template_version: rocky
resources:
  test1:
    type: OS::Heat::TestResource
    properties:
      value: test
  test2:
    type: OS::Heat::TestResource
    properties:
      value: {get_attr: [test1, output]}
  test3:
    type: OS::Heat::TestResource
    properties:
      value: test3
      fail: false
      action_wait_secs:
        update: 5
'''
        stack_identifier = self.stack_create(
            template=template)

        _template = template.replace('test1:',
                                     'test-1:').replace('fail: false',
                                                        'fail: true')
        updated_template = _template.replace(
            '{get_attr: [test1',
            '{get_attr: [test-1').replace('value: test3',
                                          'value: test-3')
        self.update_stack(stack_identifier,
                          template=updated_template,
                          expected_status='UPDATE_FAILED')
        self.update_stack(stack_identifier, template=template,
                          expected_status='UPDATE_COMPLETE')

    @test.requires_convergence
    def test_update_failed_changed_env_list_resources(self):
        template = {
            'heat_template_version': 'rocky',
            'resources': {
                'test1': {
                    'type': 'OS::Heat::TestResource',
                    'properties': {
                        'value': 'foo'
                    }
                },
                'my_res': {
                    'type': 'My::TestResource',
                    'depends_on': 'test1'
                },
                'test2': {
                    'depends_on': 'my_res',
                    'type': 'OS::Heat::TestResource'
                }
            }
        }
        env = {'resource_registry':
               {'My::TestResource': 'OS::Heat::TestResource'}}
        stack_identifier = self.stack_create(
            template=template, environment=env)
        update_template = copy.deepcopy(template)
        update_template['resources']['test1']['properties']['fail'] = 'true'
        update_template['resources']['test2']['depends_on'] = 'test1'
        del update_template['resources']['my_res']
        self.update_stack(stack_identifier,
                          template=update_template,
                          expected_status='UPDATE_FAILED')
        self.assertEqual(3, len(self.list_resources(stack_identifier)))
