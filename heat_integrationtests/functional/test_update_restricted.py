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
import time

from heat_integrationtests.functional import functional_base

test_template = {
    'heat_template_version': '2013-05-23',
    'description': 'Test template to create one instance.',
    'resources': {
        'bar': {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': '1234',
                'update_replace': False,
            }
        }
    }
}

env_both_restrict = {u'resource_registry': {
    u'resources': {
        'bar': {'restricted_actions': ['update', 'replace']}
    }
}
}

env_replace_restrict = {u'resource_registry': {
    u'resources': {
        '*ar': {'restricted_actions': 'replace'}
    }
}
}

reason_update_restrict = 'update is restricted for resource.'
reason_replace_restrict = 'replace is restricted for resource.'


class UpdateRestrictedStackTest(functional_base.FunctionalTestsBase):

    def _check_for_restriction_reason(self, events,
                                      reason, num_expected=1):
        matched = [e for e in events
                   if e.resource_status_reason == reason]
        return len(matched) == num_expected

    def test_update(self):
        stack_identifier = self.stack_create(template=test_template)

        update_template = copy.deepcopy(test_template)
        props = update_template['resources']['bar']['properties']
        props['value'] = '4567'

        # check update fails - with 'both' restricted
        self.update_stack(stack_identifier, update_template,
                          env_both_restrict,
                          expected_status='UPDATE_FAILED')

        self.assertTrue(self.verify_resource_status(stack_identifier, 'bar',
                                                    'CREATE_COMPLETE'))
        resource_events = self.client.events.list(stack_identifier, 'bar')
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_update_restrict))

        # Ensure the timestamp changes, since this will be very quick
        time.sleep(1)

        # check update succeeds - with only 'replace' restricted
        self.update_stack(stack_identifier, update_template,
                          env_replace_restrict,
                          expected_status='UPDATE_COMPLETE')

        self.assertTrue(self.verify_resource_status(stack_identifier, 'bar',
                                                    'UPDATE_COMPLETE'))
        resource_events = self.client.events.list(stack_identifier, 'bar')
        self.assertFalse(
            self._check_for_restriction_reason(resource_events,
                                               reason_update_restrict, 2))
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_replace_restrict, 0))

    def test_replace(self):
        stack_identifier = self.stack_create(template=test_template)

        update_template = copy.deepcopy(test_template)
        props = update_template['resources']['bar']['properties']
        props['value'] = '4567'
        props['update_replace'] = True

        # check replace fails - with 'both' restricted
        self.update_stack(stack_identifier, update_template,
                          env_both_restrict,
                          expected_status='UPDATE_FAILED')

        self.assertTrue(self.verify_resource_status(stack_identifier, 'bar',
                                                    'CREATE_COMPLETE'))
        resource_events = self.client.events.list(stack_identifier, 'bar')
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_replace_restrict))

        # Ensure the timestamp changes, since this will be very quick
        time.sleep(1)

        # check replace fails - with only 'replace' restricted
        self.update_stack(stack_identifier, update_template,
                          env_replace_restrict,
                          expected_status='UPDATE_FAILED')

        self.assertTrue(self.verify_resource_status(stack_identifier, 'bar',
                                                    'CREATE_COMPLETE'))
        resource_events = self.client.events.list(stack_identifier, 'bar')
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_replace_restrict, 2))
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_update_restrict, 0))

    def test_update_type_changed(self):
        stack_identifier = self.stack_create(template=test_template)

        update_template = copy.deepcopy(test_template)
        rsrc = update_template['resources']['bar']
        rsrc['type'] = 'OS::Heat::None'

        # check replace fails - with 'both' restricted
        self.update_stack(stack_identifier, update_template,
                          env_both_restrict,
                          expected_status='UPDATE_FAILED')

        self.assertTrue(self.verify_resource_status(stack_identifier, 'bar',
                                                    'CREATE_COMPLETE'))
        resource_events = self.client.events.list(stack_identifier, 'bar')
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_replace_restrict))

        # Ensure the timestamp changes, since this will be very quick
        time.sleep(1)

        # check replace fails - with only 'replace' restricted
        self.update_stack(stack_identifier, update_template,
                          env_replace_restrict,
                          expected_status='UPDATE_FAILED')

        self.assertTrue(self.verify_resource_status(stack_identifier, 'bar',
                                                    'CREATE_COMPLETE'))
        resource_events = self.client.events.list(stack_identifier, 'bar')
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_replace_restrict, 2))
        self.assertTrue(
            self._check_for_restriction_reason(resource_events,
                                               reason_update_restrict, 0))
