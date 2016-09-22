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

import time

from heat_integrationtests.functional import functional_base


class DeleteInProgressTest(functional_base.FunctionalTestsBase):

    root_template = '''
heat_template_version: 2013-05-23
resources:
    rg:
        type: OS::Heat::ResourceGroup
        properties:
            count: 125
            resource_def:
                type: empty.yaml
'''

    empty_template = '''
heat_template_version: 2013-05-23
resources:
'''

    def test_delete_nested_stacks_create_in_progress(self):
        files = {'empty.yaml': self.empty_template}
        identifier = self.stack_create(template=self.root_template,
                                       files=files,
                                       expected_status='CREATE_IN_PROGRESS')
        time.sleep(20)
        self._stack_delete(identifier)
