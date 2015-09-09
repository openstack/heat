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


class UpdatePreviewStackTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        super(UpdatePreviewStackTest, self).setUp()
        self.stack_identifier = self.stack_create(
            template=test_template_one_resource)

    def test_add_resource(self):
        result = self.preview_update_stack(self.stack_identifier,
                                           test_template_two_resource)
        changes = result['resource_changes']

        unchanged = changes['unchanged'][0]['resource_name']
        self.assertEqual('test1', unchanged)

        added = changes['added'][0]['resource_name']
        self.assertEqual('test2', added)

        empty_sections = ('updated', 'replaced', 'deleted')
        for section in empty_sections:
            self.assertEqual([], changes[section])

    def test_no_change(self):
        result = self.preview_update_stack(self.stack_identifier,
                                           test_template_one_resource)
        changes = result['resource_changes']

        unchanged = changes['unchanged'][0]['resource_name']
        self.assertEqual('test1', unchanged)

        empty_sections = ('updated', 'replaced', 'deleted', 'added')
        for section in empty_sections:
            self.assertEqual([], changes[section])

    def test_update_resource(self):
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

        empty_sections = ('added', 'unchanged', 'replaced', 'deleted')
        for section in empty_sections:
            self.assertEqual([], changes[section])

    def test_replaced_resource(self):
        orig_template = {
            'heat_template_version': '2013-05-23',
            'description': 'Test template to create one instance.',
            'resources': {
                'test1': {
                    'type': 'OS::Heat::TestResource',
                    'properties': {
                        'update_replace': False,
                    }
                }
            }
        }

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

        stack_identifier = self.stack_create(template=orig_template)
        result = self.preview_update_stack(stack_identifier, new_template)
        changes = result['resource_changes']

        replaced = changes['replaced'][0]['resource_name']
        self.assertEqual('test1', replaced)

        empty_sections = ('added', 'unchanged', 'updated', 'deleted')
        for section in empty_sections:
            self.assertEqual([], changes[section])

    def test_delete_resource(self):
        stack_identifier = self.stack_create(
            template=test_template_two_resource)
        result = self.preview_update_stack(stack_identifier,
                                           test_template_one_resource)
        changes = result['resource_changes']

        unchanged = changes['unchanged'][0]['resource_name']
        self.assertEqual('test1', unchanged)

        deleted = changes['deleted'][0]['resource_name']
        self.assertEqual('test2', deleted)

        empty_sections = ('updated', 'replaced', 'added')
        for section in empty_sections:
            self.assertEqual([], changes[section])
