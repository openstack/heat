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

import mock

from heat.engine import service_stack_watch
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests import utils


class StackServiceWatcherTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceWatcherTest, self).setUp()
        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')

    @mock.patch.object(service_stack_watch.stack_object.Stack,
                       'get_all_by_owner_id')
    @mock.patch.object(service_stack_watch.watch_rule_object.WatchRule,
                       'get_all_by_stack')
    @mock.patch.object(service_stack_watch.watch_rule_object.WatchRule,
                       'update_by_id')
    def test_periodic_watch_task_not_created(self, watch_rule_update,
                                             watch_rule_get_all_by_stack,
                                             stack_get_all_by_owner_id):
        """Test case for not creating periodic task for cloud watch lite alarm.

        If there is no cloud watch lite alarm, then don't create a periodic
        task for it.
        """
        stack_id = 83
        watch_rule_get_all_by_stack.return_value = []
        stack_get_all_by_owner_id.return_value = []
        tg = mock.Mock()
        sw = service_stack_watch.StackWatch(tg)
        sw.start_watch_task(stack_id, self.ctx)

        # assert that add_timer is NOT called.
        self.assertEqual([], tg.add_timer.call_args_list)

    @mock.patch.object(service_stack_watch.stack_object.Stack,
                       'get_all_by_owner_id')
    @mock.patch.object(service_stack_watch.watch_rule_object.WatchRule,
                       'get_all_by_stack')
    @mock.patch.object(service_stack_watch.watch_rule_object.WatchRule,
                       'update_by_id')
    def test_periodic_watch_task_created(self, watch_rule_update,
                                         watch_rule_get_all_by_stack,
                                         stack_get_all_by_owner_id):
        """Test case for creating periodic task for cloud watch lite alarm.

        If there is no cloud watch lite alarm, then DO create a periodic task
        for it.
        """
        stack_id = 86
        wr1 = mock.Mock()
        wr1.id = 4
        wr1.state = rpc_api.WATCH_STATE_NODATA

        watch_rule_get_all_by_stack.return_value = [wr1]
        stack_get_all_by_owner_id.return_value = []
        tg = mock.Mock()
        sw = service_stack_watch.StackWatch(tg)
        sw.start_watch_task(stack_id, self.ctx)

        # assert that add_timer IS called.
        self.assertEqual([mock.call(stack_id, sw.periodic_watcher_task,
                                    sid=stack_id)],
                         tg.add_timer.call_args_list)

    @mock.patch.object(service_stack_watch.stack_object.Stack,
                       'get_all_by_owner_id')
    @mock.patch.object(service_stack_watch.watch_rule_object.WatchRule,
                       'get_all_by_stack')
    @mock.patch.object(service_stack_watch.watch_rule_object.WatchRule,
                       'update_by_id')
    def test_periodic_watch_task_created_nested(self, watch_rule_update,
                                                watch_rule_get_all_by_stack,
                                                stack_get_all_by_owner_id):
        stack_id = 90

        def my_wr_get(cnxt, sid):
            if sid == stack_id:
                return []
            wr1 = mock.Mock()
            wr1.id = 4
            wr1.state = rpc_api.WATCH_STATE_NODATA
            return [wr1]

        watch_rule_get_all_by_stack.side_effect = my_wr_get

        def my_nested_get(cnxt, sid):
            if sid == stack_id:
                nested_stack = mock.Mock()
                nested_stack.id = 55
                return [nested_stack]
            return []

        stack_get_all_by_owner_id.side_effect = my_nested_get
        tg = mock.Mock()
        sw = service_stack_watch.StackWatch(tg)
        sw.start_watch_task(stack_id, self.ctx)

        # assert that add_timer IS called.
        self.assertEqual([mock.call(stack_id, sw.periodic_watcher_task,
                                    sid=stack_id)],
                         tg.add_timer.call_args_list)
