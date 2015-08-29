#
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

from oslo_config import cfg

cfg.CONF.import_opt('stack_scheduler_hints', 'heat.common.config')


class SchedulerHintsMixin(object):
    '''
    Utility class to encapsulate Scheduler Hint related logic shared
    between resources.
    '''

    HEAT_ROOT_STACK_ID = 'heat_root_stack_id'
    HEAT_STACK_ID = 'heat_stack_id'
    HEAT_STACK_NAME = 'heat_stack_name'
    HEAT_PATH_IN_STACK = 'heat_path_in_stack'
    HEAT_RESOURCE_NAME = 'heat_resource_name'
    HEAT_RESOURCE_UUID = 'heat_resource_uuid'

    def _scheduler_hints(self, scheduler_hints):
        '''Augment scheduler hints with supplemental content.'''
        if cfg.CONF.stack_scheduler_hints:
            if scheduler_hints is None:
                scheduler_hints = {}
            scheduler_hints[self.HEAT_ROOT_STACK_ID] = \
                self.stack.root_stack_id()
            scheduler_hints[self.HEAT_STACK_ID] = self.stack.id
            scheduler_hints[self.HEAT_STACK_NAME] = self.stack.name
            scheduler_hints[self.HEAT_PATH_IN_STACK] = \
                self.stack.path_in_stack()
            scheduler_hints[self.HEAT_RESOURCE_NAME] = self.name
            scheduler_hints[self.HEAT_RESOURCE_UUID] = self.uuid
        return scheduler_hints
