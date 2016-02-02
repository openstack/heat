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

from heat_integrationtests.common import test


class ScenarioTestsBase(test.HeatIntegrationTest):
    """This class defines common parameters for scenario tests."""

    def setUp(self):
        super(ScenarioTestsBase, self).setUp()
        self.check_skip()

        self.client = self.orchestration_client
        self.sub_dir = 'templates'
        self.assign_keypair()

        if not self.conf.fixed_network_name:
            raise self.skipException("No default network configured to test")
        self.net = self._get_network()

        if not self.conf.image_ref:
            raise self.skipException("No image configured to test")
        if not self.conf.instance_type:
            raise self.skipException("No flavor configured to test")

        if not self.conf.minimal_image_ref:
            raise self.skipException("No minimal image configured to test")
        if not self.conf.minimal_instance_type:
            raise self.skipException("No minimal flavor configured to test")

    def launch_stack(self, template_name, expected_status='CREATE_COMPLETE',
                     parameters=None, **kwargs):
        template = self._load_template(__file__, template_name, self.sub_dir)

        parameters = parameters or {}

        if kwargs.get('add_parameters'):
            parameters.update(kwargs['add_parameters'])

        stack_id = self.stack_create(
            stack_name=kwargs.get('stack_name'),
            template=template,
            files=kwargs.get('files'),
            parameters=parameters,
            environment=kwargs.get('environment'),
            expected_status=expected_status
        )

        return stack_id

    def check_skip(self):
        test_cls_name = self.__class__.__name__
        test_method_name = '.'.join([test_cls_name, self._testMethodName])
        test_skipped = (self.conf.skip_scenario_test_list and (
            test_cls_name in self.conf.skip_scenario_test_list or
            test_method_name in self.conf.skip_scenario_test_list))
        if self.conf.skip_scenario_tests or test_skipped:
            self.skipTest('Test disabled in conf, skipping')
