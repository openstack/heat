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

from heat_integrationtests.functional import functional_base

test_template_one_resource = {
    'heat_template_version': '2013-05-23',
    'description': 'Test template to create one instance.',
    'resources': {
        'test1': {
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

test_template_two_resource = {
    'heat_template_version': '2013-05-23',
    'description': 'Test template to create two instance.',
    'resources': {
        'test1': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'Test1',
                'fail': False,
                'update_replace': False,
                'wait_secs': 0
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


class UpdatePreviewBase(functional_base.FunctionalTestsBase):

    def assert_empty_sections(self, changes, empty_sections):
        for section in empty_sections:
            self.assertEqual([], changes[section])


class UpdatePreviewStackTest(UpdatePreviewBase):

    def test_add_resource(self):
        self.stack_identifier = self.stack_create(
            template=test_template_one_resource)
        result = self.preview_update_stack(self.stack_identifier,
                                           test_template_two_resource)
        changes = result['resource_changes']

        unchanged = changes['unchanged'][0]['resource_name']
        self.assertEqual('test1', unchanged)

        added = changes['added'][0]['resource_name']
        self.assertEqual('test2', added)

        self.assert_empty_sections(changes, ['updated', 'replaced', 'deleted'])

    def test_no_change(self):
        self.stack_identifier = self.stack_create(
            template=test_template_one_resource)
        result = self.preview_update_stack(self.stack_identifier,
                                           test_template_one_resource)
        changes = result['resource_changes']

        unchanged = changes['unchanged'][0]['resource_name']
        self.assertEqual('test1', unchanged)

        self.assert_empty_sections(
            changes, ['updated', 'replaced', 'deleted', 'added'])

    def test_update_resource(self):
        self.stack_identifier = self.stack_create(
            template=test_template_one_resource)
        test_template_updated_resource = {
            'heat_template_version': '2013-05-23',
            'description': 'Test template to create one instance.',
            'resources': {
                'test1': {
                    'type': 'OS::Heat::TestResource',
                    'properties': {
                        'value': 'Test1 foo',
                        'fail': False,
                        'update_replace': False,
                        'wait_secs': 0
                    }
                }
            }
        }

        result = self.preview_update_stack(self.stack_identifier,
                                           test_template_updated_resource)
        changes = result['resource_changes']

        updated = changes['updated'][0]['resource_name']
        self.assertEqual('test1', updated)

        self.assert_empty_sections(
            changes, ['added', 'unchanged', 'replaced', 'deleted'])

    def test_replaced_resource(self):
        self.stack_identifier = self.stack_create(
            template=test_template_one_resource)
        new_template = {
            'heat_template_version': '2013-05-23',
            'description': 'Test template to create one instance.',
            'resources': {
                'test1': {
                    'type': 'OS::Heat::TestResource',
                    'properties': {
                        'update_replace': True,
                    }
                }
            }
        }

        result = self.preview_update_stack(self.stack_identifier, new_template)
        changes = result['resource_changes']

        replaced = changes['replaced'][0]['resource_name']
        self.assertEqual('test1', replaced)

        self.assert_empty_sections(
            changes, ['added', 'unchanged', 'updated', 'deleted'])

    def test_delete_resource(self):
        self.stack_identifier = self.stack_create(
            template=test_template_two_resource)
        result = self.preview_update_stack(self.stack_identifier,
                                           test_template_one_resource)
        changes = result['resource_changes']

        unchanged = changes['unchanged'][0]['resource_name']
        self.assertEqual('test1', unchanged)

        deleted = changes['deleted'][0]['resource_name']
        self.assertEqual('test2', deleted)

        self.assert_empty_sections(changes, ['updated', 'replaced', 'added'])


class UpdatePreviewStackTestNested(UpdatePreviewBase):
    template_nested_parent = '''
heat_template_version: 2016-04-08
resources:
  nested1:
    type: nested1.yaml
'''

    template_nested1 = '''
heat_template_version: 2016-04-08
resources:
  nested2:
    type: nested2.yaml
'''

    template_nested2 = '''
heat_template_version: 2016-04-08
resources:
  random:
    type: OS::Heat::RandomString
'''

    template_nested2_2 = '''
heat_template_version: 2016-04-08
resources:
  random:
    type: OS::Heat::RandomString
  random2:
    type: OS::Heat::RandomString
'''

    def _get_by_resource_name(self, changes, name, action):
        filtered_l = [x for x in changes[action]
                      if x['resource_name'] == name]
        self.assertEqual(1, len(filtered_l))
        return filtered_l[0]

    def test_nested_resources_nochange(self):
        files = {'nested1.yaml': self.template_nested1,
                 'nested2.yaml': self.template_nested2}
        self.stack_identifier = self.stack_create(
            template=self.template_nested_parent, files=files)
        result = self.preview_update_stack(
            self.stack_identifier,
            template=self.template_nested_parent,
            files=files, show_nested=True)
        changes = result['resource_changes']

        # The nested random resource should be unchanged, but we always
        # update nested stacks even when there are no changes
        self.assertEqual(1, len(changes['unchanged']))
        self.assertEqual('random', changes['unchanged'][0]['resource_name'])
        self.assertEqual('nested2', changes['unchanged'][0]['parent_resource'])

        self.assertEqual(2, len(changes['updated']))
        u_nested1 = self._get_by_resource_name(changes, 'nested1', 'updated')
        self.assertNotIn('parent_resource', u_nested1)
        u_nested2 = self._get_by_resource_name(changes, 'nested2', 'updated')
        self.assertEqual('nested1', u_nested2['parent_resource'])

        self.assert_empty_sections(changes, ['replaced', 'deleted', 'added'])

    def test_nested_resources_add(self):
        files = {'nested1.yaml': self.template_nested1,
                 'nested2.yaml': self.template_nested2}
        self.stack_identifier = self.stack_create(
            template=self.template_nested_parent, files=files)
        files['nested2.yaml'] = self.template_nested2_2
        result = self.preview_update_stack(
            self.stack_identifier,
            template=self.template_nested_parent,
            files=files, show_nested=True)
        changes = result['resource_changes']

        # The nested random resource should be unchanged, but we always
        # update nested stacks even when there are no changes
        self.assertEqual(1, len(changes['unchanged']))
        self.assertEqual('random', changes['unchanged'][0]['resource_name'])
        self.assertEqual('nested2', changes['unchanged'][0]['parent_resource'])

        self.assertEqual(1, len(changes['added']))
        self.assertEqual('random2', changes['added'][0]['resource_name'])
        self.assertEqual('nested2', changes['added'][0]['parent_resource'])

        self.assert_empty_sections(changes, ['replaced', 'deleted'])

    def test_nested_resources_delete(self):
        files = {'nested1.yaml': self.template_nested1,
                 'nested2.yaml': self.template_nested2_2}
        self.stack_identifier = self.stack_create(
            template=self.template_nested_parent, files=files)
        files['nested2.yaml'] = self.template_nested2
        result = self.preview_update_stack(
            self.stack_identifier,
            template=self.template_nested_parent,
            files=files, show_nested=True)
        changes = result['resource_changes']

        # The nested random resource should be unchanged, but we always
        # update nested stacks even when there are no changes
        self.assertEqual(1, len(changes['unchanged']))
        self.assertEqual('random', changes['unchanged'][0]['resource_name'])
        self.assertEqual('nested2', changes['unchanged'][0]['parent_resource'])

        self.assertEqual(1, len(changes['deleted']))
        self.assertEqual('random2', changes['deleted'][0]['resource_name'])
        self.assertEqual('nested2', changes['deleted'][0]['parent_resource'])

        self.assert_empty_sections(changes, ['replaced', 'added'])

    def test_nested_resources_replace(self):
        files = {'nested1.yaml': self.template_nested1,
                 'nested2.yaml': self.template_nested2}
        self.stack_identifier = self.stack_create(
            template=self.template_nested_parent, files=files)
        parent_none = self.template_nested_parent.replace(
            'nested1.yaml', 'OS::Heat::None')
        result = self.preview_update_stack(
            self.stack_identifier,
            template=parent_none,
            show_nested=True)
        changes = result['resource_changes']

        # The nested random resource should be unchanged, but we always
        # update nested stacks even when there are no changes
        self.assertEqual(1, len(changes['replaced']))
        self.assertEqual('nested1', changes['replaced'][0]['resource_name'])

        self.assertEqual(2, len(changes['deleted']))
        d_random = self._get_by_resource_name(changes, 'random', 'deleted')
        self.assertEqual('nested2', d_random['parent_resource'])
        d_nested2 = self._get_by_resource_name(changes, 'nested2', 'deleted')
        self.assertEqual('nested1', d_nested2['parent_resource'])

        self.assert_empty_sections(changes, ['updated', 'unchanged', 'added'])
