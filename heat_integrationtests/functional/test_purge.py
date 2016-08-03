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

from oslo_concurrency import processutils

from heat_integrationtests.functional import functional_base


class PurgeTest(functional_base.FunctionalTestsBase):
    template = '''
heat_template_version: 2014-10-16
parameters:
resources:
  test_resource:
    type: OS::Heat::TestResource
'''

    def test_purge(self):
        stack_identifier = self.stack_create(template=self.template)
        self._stack_delete(stack_identifier)
        stacks = dict((stack.id, stack) for stack in
                      self.client.stacks.list(show_deleted=True))
        self.assertIn(stack_identifier.split('/')[1], stacks)
        time.sleep(1)
        cmd = "heat-manage purge_deleted 0"
        processutils.execute(cmd, shell=True)
        stacks = dict((stack.id, stack) for stack in
                      self.client.stacks.list(show_deleted=True))
        self.assertNotIn(stack_identifier.split('/')[1], stacks)

        # Test with tags
        stack_identifier = self.stack_create(template=self.template,
                                             tags="foo,bar")
        self._stack_delete(stack_identifier)
        time.sleep(1)
        cmd = "heat-manage purge_deleted 0"
        processutils.execute(cmd, shell=True)
        stacks = dict((stack.id, stack) for stack in
                      self.client.stacks.list(show_deleted=True))
        self.assertNotIn(stack_identifier.split('/')[1], stacks)
