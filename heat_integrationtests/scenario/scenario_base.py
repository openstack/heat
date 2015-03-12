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
    "This class define common parameters for scenario tests"

    def setUp(self):
        super(ScenarioTestsBase, self).setUp()
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
