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

from oslo_log import log as logging
from oslo_utils import timeutils
import six

from heat.common import context
from heat.engine import stack
from heat.engine import watchrule
from heat.objects import stack as stack_object
from heat.objects import watch_rule as watch_rule_object
from heat.rpc import api as rpc_api

LOG = logging.getLogger(__name__)


class StackWatch(object):
    def __init__(self, thread_group_mgr):
        self.thread_group_mgr = thread_group_mgr

    def start_watch_task(self, stack_id, cnxt):

        def stack_has_a_watchrule(sid):
            wrs = watch_rule_object.WatchRule.get_all_by_stack(cnxt, sid)

            now = timeutils.utcnow()
            start_watch_thread = False
            for wr in wrs:
                # reset the last_evaluated so we don't fire off alarms when
                # the engine has not been running.
                watch_rule_object.WatchRule.update_by_id(
                    cnxt, wr.id,
                    {'last_evaluated': now})

                if wr.state != rpc_api.WATCH_STATE_CEILOMETER_CONTROLLED:
                    start_watch_thread = True

            children = stack_object.Stack.get_all_by_owner_id(cnxt, sid)
            for child in children:
                if stack_has_a_watchrule(child.id):
                    start_watch_thread = True

            return start_watch_thread

        if stack_has_a_watchrule(stack_id):
            self.thread_group_mgr.add_timer(
                stack_id,
                self.periodic_watcher_task,
                sid=stack_id)

    def check_stack_watches(self, sid):
        # Use admin_context for stack_get to defeat tenant
        # scoping otherwise we fail to retrieve the stack
        LOG.debug("Periodic watcher task for stack %s", sid)
        admin_context = context.get_admin_context()
        db_stack = stack_object.Stack.get_by_id(admin_context,
                                                sid)
        if not db_stack:
            LOG.error("Unable to retrieve stack %s for periodic task", sid)
            return
        stk = stack.Stack.load(admin_context, stack=db_stack,
                               use_stored_context=True)

        # recurse into any nested stacks.
        children = stack_object.Stack.get_all_by_owner_id(admin_context, sid)
        for child in children:
            self.check_stack_watches(child.id)

        # Get all watchrules for this stack and evaluate them
        try:
            wrs = watch_rule_object.WatchRule.get_all_by_stack(admin_context,
                                                               sid)
        except Exception as ex:
            LOG.warning('periodic_task db error watch rule removed? %(ex)s',
                        ex)
            return

        def run_alarm_action(stk, actions, details):
            for action in actions:
                action(details=details)
            for res in six.itervalues(stk):
                res.metadata_update()

        for wr in wrs:
            rule = watchrule.WatchRule.load(stk.context, watch=wr)
            actions = rule.evaluate()
            if actions:
                self.thread_group_mgr.start(sid, run_alarm_action, stk,
                                            actions, rule.get_details())

    def periodic_watcher_task(self, sid):
        """Evaluate all watch-rules defined for stack ID.

        Periodic task, created for each stack, triggers watch-rule evaluation
        for all rules defined for the stack sid = stack ID.
        """
        self.check_stack_watches(sid)
