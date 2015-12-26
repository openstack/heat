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

import yaml

from heat_integrationtests.functional import functional_base


class HooksTest(functional_base.FunctionalTestsBase):

    def setUp(self):
        super(HooksTest, self).setUp()
        self.template = {'heat_template_version': '2014-10-16',
                         'resources': {
                             'foo_step1': {'type': 'OS::Heat::RandomString'},
                             'foo_step2': {'type': 'OS::Heat::RandomString',
                                           'depends_on': 'foo_step1'},
                             'foo_step3': {'type': 'OS::Heat::RandomString',
                                           'depends_on': 'foo_step2'}}}

    def test_hook_pre_create(self):
        env = {'resource_registry':
               {'resources':
                {'foo_step2':
                 {'hooks': 'pre-create'}}}}
        # Note we don't wait for CREATE_COMPLETE, because we need to
        # signal to clear the hook before create will complete
        stack_identifier = self.stack_create(
            template=self.template,
            environment=env,
            expected_status='CREATE_IN_PROGRESS')
        self._wait_for_resource_status(
            stack_identifier, 'foo_step1', 'CREATE_COMPLETE')
        self._wait_for_resource_status(
            stack_identifier, 'foo_step2', 'INIT_COMPLETE')
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='CREATE paused until Hook pre-create is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('INIT_COMPLETE', ev[0].resource_status)
        self.client.resources.signal(stack_identifier, 'foo_step2',
                                     data={'unset_hook': 'pre-create'})
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='Hook pre-create is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('INIT_COMPLETE', ev[0].resource_status)
        self._wait_for_resource_status(
            stack_identifier, 'foo_step2', 'CREATE_COMPLETE')
        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')

    def test_hook_pre_update_nochange(self):
        env = {'resource_registry':
               {'resources':
                {'foo_step2':
                 {'hooks': 'pre-update'}}}}
        stack_identifier = self.stack_create(
            template=self.template,
            environment=env)
        res_before = self.client.resources.get(stack_identifier, 'foo_step2')
        # Note we don't wait for UPDATE_COMPLETE, because we need to
        # signal to clear the hook before update will complete
        self.update_stack(
            stack_identifier,
            template=self.template,
            environment=env,
            expected_status='UPDATE_IN_PROGRESS')

        # Note when a hook is specified, the resource status doesn't change
        # when we hit the hook, so we look for the event, then assert the
        # state is unchanged.
        self._wait_for_resource_status(
            stack_identifier, 'foo_step2', 'CREATE_COMPLETE')
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='UPDATE paused until Hook pre-update is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('CREATE_COMPLETE', ev[0].resource_status)
        self.client.resources.signal(stack_identifier, 'foo_step2',
                                     data={'unset_hook': 'pre-update'})
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='Hook pre-update is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('CREATE_COMPLETE', ev[0].resource_status)
        self._wait_for_resource_status(
            stack_identifier, 'foo_step2', 'CREATE_COMPLETE')
        self._wait_for_stack_status(stack_identifier, 'UPDATE_COMPLETE')
        res_after = self.client.resources.get(stack_identifier, 'foo_step2')
        self.assertEqual(res_before.physical_resource_id,
                         res_after.physical_resource_id)

    def test_hook_pre_update_replace(self):
        env = {'resource_registry':
               {'resources':
                {'foo_step2':
                 {'hooks': 'pre-update'}}}}
        stack_identifier = self.stack_create(
            template=self.template,
            environment=env)
        res_before = self.client.resources.get(stack_identifier, 'foo_step2')
        # Note we don't wait for UPDATE_COMPLETE, because we need to
        # signal to clear the hook before update will complete
        self.template['resources']['foo_step2']['properties'] = {'length': 10}
        self.update_stack(
            stack_identifier,
            template=self.template,
            environment=env,
            expected_status='UPDATE_IN_PROGRESS')

        # Note when a hook is specified, the resource status doesn't change
        # when we hit the hook, so we look for the event, then assert the
        # state is unchanged.
        self._wait_for_resource_status(
            stack_identifier, 'foo_step2', 'CREATE_COMPLETE')
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='UPDATE paused until Hook pre-update is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('CREATE_COMPLETE', ev[0].resource_status)
        self.client.resources.signal(stack_identifier, 'foo_step2',
                                     data={'unset_hook': 'pre-update'})
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='Hook pre-update is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('CREATE_COMPLETE', ev[0].resource_status)
        self._wait_for_resource_status(
            stack_identifier, 'foo_step2', 'CREATE_COMPLETE')
        self._wait_for_stack_status(stack_identifier, 'UPDATE_COMPLETE')
        res_after = self.client.resources.get(stack_identifier, 'foo_step2')
        self.assertNotEqual(res_before.physical_resource_id,
                            res_after.physical_resource_id)

    def test_hook_pre_update_in_place(self):
        env = {'resource_registry':
               {'resources':
                {'rg':
                 {'hooks': 'pre-update'}}}}
        template = {'heat_template_version': '2014-10-16',
                    'resources': {
                        'rg': {
                            'type': 'OS::Heat::ResourceGroup',
                            'properties': {
                                'count': 1,
                                'resource_def': {
                                    'type': 'OS::Heat::RandomString'}}}}}
        # Note we don't wait for CREATE_COMPLETE, because we need to
        # signal to clear the hook before create will complete
        stack_identifier = self.stack_create(
            template=template,
            environment=env)
        res_before = self.client.resources.get(stack_identifier, 'rg')
        template['resources']['rg']['properties']['count'] = 2
        self.update_stack(
            stack_identifier,
            template=template,
            environment=env,
            expected_status='UPDATE_IN_PROGRESS')

        # Note when a hook is specified, the resource status doesn't change
        # when we hit the hook, so we look for the event, then assert the
        # state is unchanged.
        self._wait_for_resource_status(
            stack_identifier, 'rg', 'CREATE_COMPLETE')
        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='UPDATE paused until Hook pre-update is cleared',
            rsrc_name='rg')
        self.assertEqual('CREATE_COMPLETE', ev[0].resource_status)
        self.client.resources.signal(stack_identifier, 'rg',
                                     data={'unset_hook': 'pre-update'})

        ev = self.wait_for_event_with_reason(
            stack_identifier,
            reason='Hook pre-update is cleared',
            rsrc_name='rg')
        self.assertEqual('CREATE_COMPLETE', ev[0].resource_status)
        self._wait_for_stack_status(stack_identifier, 'UPDATE_COMPLETE')
        res_after = self.client.resources.get(stack_identifier, 'rg')
        self.assertEqual(res_before.physical_resource_id,
                         res_after.physical_resource_id)

    def test_hook_pre_create_nested(self):
        files = {'nested.yaml': yaml.dump(self.template)}
        env = {'resource_registry':
               {'resources':
                {'nested':
                 {'foo_step2':
                  {'hooks': 'pre-create'}}}}}
        template = {'heat_template_version': '2014-10-16',
                    'resources': {
                        'nested': {'type': 'nested.yaml'}}}
        # Note we don't wait for CREATE_COMPLETE, because we need to
        # signal to clear the hook before create will complete
        stack_identifier = self.stack_create(
            template=template,
            environment=env,
            files=files,
            expected_status='CREATE_IN_PROGRESS')
        self._wait_for_resource_status(stack_identifier, 'nested',
                                       'CREATE_IN_PROGRESS')
        nested_identifier = self.assert_resource_is_a_stack(
            stack_identifier, 'nested', wait=True)
        self._wait_for_resource_status(
            nested_identifier, 'foo_step1', 'CREATE_COMPLETE')
        self._wait_for_resource_status(
            nested_identifier, 'foo_step2', 'INIT_COMPLETE')
        ev = self.wait_for_event_with_reason(
            nested_identifier,
            reason='CREATE paused until Hook pre-create is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('INIT_COMPLETE', ev[0].resource_status)
        self.client.resources.signal(nested_identifier, 'foo_step2',
                                     data={'unset_hook': 'pre-create'})
        ev = self.wait_for_event_with_reason(
            nested_identifier,
            reason='Hook pre-create is cleared',
            rsrc_name='foo_step2')
        self.assertEqual('INIT_COMPLETE', ev[0].resource_status)
        self._wait_for_resource_status(
            nested_identifier, 'foo_step2', 'CREATE_COMPLETE')
        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')

    def test_hook_pre_create_wildcard(self):
        env = {'resource_registry':
               {'resources':
                {'foo_*':
                 {'hooks': 'pre-create'}}}}
        # Note we don't wait for CREATE_COMPLETE, because we need to
        # signal to clear the hook before create will complete
        stack_identifier = self.stack_create(
            template=self.template,
            environment=env,
            expected_status='CREATE_IN_PROGRESS')
        self._wait_for_resource_status(
            stack_identifier, 'foo_step1', 'INIT_COMPLETE')
        self.wait_for_event_with_reason(
            stack_identifier,
            reason='CREATE paused until Hook pre-create is cleared',
            rsrc_name='foo_step1')
        self.client.resources.signal(stack_identifier, 'foo_step1',
                                     data={'unset_hook': 'pre-create'})
        self.wait_for_event_with_reason(
            stack_identifier,
            reason='Hook pre-create is cleared',
            rsrc_name='foo_step1')
        self._wait_for_resource_status(
            stack_identifier, 'foo_step2', 'INIT_COMPLETE')
        self.wait_for_event_with_reason(
            stack_identifier,
            reason='CREATE paused until Hook pre-create is cleared',
            rsrc_name='foo_step2')
        self.client.resources.signal(stack_identifier, 'foo_step2',
                                     data={'unset_hook': 'pre-create'})
        self.wait_for_event_with_reason(
            stack_identifier,
            reason='Hook pre-create is cleared',
            rsrc_name='foo_step2')
        self._wait_for_resource_status(
            stack_identifier, 'foo_step3', 'INIT_COMPLETE')
        self.wait_for_event_with_reason(
            stack_identifier,
            reason='CREATE paused until Hook pre-create is cleared',
            rsrc_name='foo_step3')
        self.client.resources.signal(stack_identifier, 'foo_step3',
                                     data={'unset_hook': 'pre-create'})
        self.wait_for_event_with_reason(
            stack_identifier,
            reason='Hook pre-create is cleared',
            rsrc_name='foo_step3')
        self._wait_for_stack_status(stack_identifier, 'CREATE_COMPLETE')
