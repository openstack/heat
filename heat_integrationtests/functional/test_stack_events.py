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


class StackEventsTest(functional_base.FunctionalTestsBase):

    template = '''
heat_template_version: 2014-10-16
parameters:
resources:
  test_resource:
    type: OS::Heat::TestResource
    properties:
      value: 'test1'
      fail: False
      update_replace: False
      wait_secs: 0
outputs:
  resource_id:
    description: 'ID of resource'
    value: { get_resource: test_resource }
'''

    def setUp(self):
        super(StackEventsTest, self).setUp()

    def _verify_event_fields(self, event, event_characteristics):
        self.assertIsNotNone(event_characteristics)
        self.assertIsNotNone(event.event_time)
        self.assertIsNotNone(event.links)
        self.assertIsNotNone(event.logical_resource_id)
        self.assertIsNotNone(event.resource_status)
        self.assertIn(event.resource_status, event_characteristics[1])
        self.assertIsNotNone(event.resource_status_reason)
        self.assertIsNotNone(event.id)

    def test_event(self):
        parameters = {}

        test_stack_name = self._stack_rand_name()
        stack_identifier = self.stack_create(
            stack_name=test_stack_name,
            template=self.template,
            parameters=parameters
        )

        expected_status = ['CREATE_IN_PROGRESS', 'CREATE_COMPLETE']
        event_characteristics = {
            test_stack_name: ('OS::Heat::Stack', expected_status),
            'test_resource': ('OS::Heat::TestResource', expected_status)}

        # List stack events
        # API: GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/events
        stack_events = self.client.events.list(stack_identifier)

        for stack_event in stack_events:
            # Key on an expected/valid resource name
            self._verify_event_fields(
                stack_event,
                event_characteristics[stack_event.resource_name])

            # Test the event filtering API based on this resource_name
            # /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/events
            resource_events = self.client.events.list(
                stack_identifier,
                stack_event.resource_name)

            # Resource events are a subset of the original stack event list
            self.assertTrue(len(resource_events) < len(stack_events))

            # Get the event details for each resource event
            for resource_event in resource_events:
                # A resource_event should be in the original stack event list
                self.assertIn(resource_event, stack_events)
                # Given a filtered list, the resource names should be identical
                self.assertEqual(
                    resource_event.resource_name,
                    stack_event.resource_name)
                # Verify all fields, keying off the resource_name
                self._verify_event_fields(
                    resource_event,
                    event_characteristics[resource_event.resource_name])

                # Exercise the event details API
                # /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/events/{event_id}
                event_details = self.client.events.get(
                    stack_identifier,
                    resource_event.resource_name,
                    resource_event.id)
                self._verify_event_fields(
                    event_details,
                    event_characteristics[event_details.resource_name])
                # The names should be identical to the non-detailed event
                self.assertEqual(
                    resource_event.resource_name,
                    event_details.resource_name)
                # Verify the extra field in the detail results
                self.assertIsNotNone(event_details.resource_type)
                self.assertEqual(
                    event_characteristics[event_details.resource_name][0],
                    event_details.resource_type)
