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

from oslo.config import cfg

from heat.openstack.common import timeutils

from heat.engine import environment
from heat.engine import parser
from heat.engine import resource

from heat.tests import generic_resource
from heat.tests import utils
from heat.tests import common


class NotificationTest(common.HeatTestCase):

    def setUp(self):
        super(NotificationTest, self).setUp()
        utils.setup_dummy_db()

        cfg.CONF.import_opt('notification_driver',
                            'heat.openstack.common.notifier.api')

        cfg.CONF.set_default('notification_driver',
                             ['heat.openstack.common.notifier.test_notifier'])
        cfg.CONF.set_default('host', 'test_host')
        resource._register_class('GenericResource',
                                 generic_resource.ResourceWithProps)

    def create_test_stack(self):
        test_template = {'Parameters': {'Foo': {'Type': 'String'},
                                        'Pass': {'Type': 'String',
                                                 'NoEcho': True}},
                         'Resources':
                         {'TestResource': {'Type': 'GenericResource',
                                           'Properties': {'Foo': 'abc'}}},
                         'Outputs': {'food':
                                     {'Value':
                                      {'Fn::GetAtt': ['TestResource',
                                                      'foo']}}}}
        template = parser.Template(test_template)
        self.ctx = utils.dummy_context()
        self.ctx.tenant_id = 'test_tenant'

        env = environment.Environment()
        env.load({u'parameters':
                  {u'Foo': 'user_data', u'Pass': 'secret'}})
        self.stack_name = utils.random_name()
        stack = parser.Stack(self.ctx, self.stack_name, template,
                             env=env, disable_rollback=True)
        self.stack = stack
        stack.store()
        self.created_time = stack.created_time
        self.create_at = timeutils.isotime(self.created_time)
        stack.create()

        self.expected = {}
        for action in ('create', 'suspend', 'delete'):
            self.make_mocks(action)

    def make_mocks(self, action):
        stack_arn = self.stack.identifier().arn()
        self.expected[action] = [
            mock.call(self.ctx,
                      'orchestration.test_host',
                      'orchestration.%s.start' % action,
                      'INFO',
                      {'state_reason': 'Stack %s started' % action.upper(),
                       'user_id': 'test_username',
                       'stack_identity': stack_arn,
                       'tenant_id': 'test_tenant',
                       'create_at': self.create_at,
                       'stack_name': self.stack_name,
                       'state': '%s_IN_PROGRESS' % action.upper()}),
            mock.call(self.ctx, 'orchestration.test_host',
                      'orchestration.%s.end' % action,
                      'INFO',
                      {'state_reason':
                       'Stack %s completed successfully' % action,
                       'user_id': 'test_username',
                       'stack_identity': stack_arn,
                       'tenant_id': 'test_tenant',
                       'create_at': self.create_at,
                       'stack_name': self.stack_name,
                       'state': '%s_COMPLETE' % action.upper()})]

    @utils.stack_delete_after
    def test_create_stack(self):
        with mock.patch('heat.openstack.common.notifier.api.notify') \
                as mock_notify:
            self.create_test_stack()
            self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                             self.stack.state)

            self.assertEqual(self.expected['create'],
                             mock_notify.call_args_list)

    @utils.stack_delete_after
    def test_create_and_suspend_stack(self):
        with mock.patch('heat.openstack.common.notifier.api.notify') \
                as mock_notify:
            self.create_test_stack()
            self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                             self.stack.state)

            self.assertEqual(self.expected['create'],
                             mock_notify.call_args_list)
            self.stack.suspend()
            self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                             self.stack.state)

            expected = self.expected['create'] + self.expected['suspend']
            self.assertEqual(expected, mock_notify.call_args_list)

    @utils.stack_delete_after
    def test_create_and_delete_stack(self):
        with mock.patch('heat.openstack.common.notifier.api.notify') \
                as mock_notify:
            self.create_test_stack()
            self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                             self.stack.state)

            self.assertEqual(self.expected['create'],
                             mock_notify.call_args_list)
            self.stack.delete()
            self.assertEqual((self.stack.DELETE, self.stack.COMPLETE),
                             self.stack.state)
            expected = self.expected['create'] + self.expected['delete']

            expected = self.expected['create'] + self.expected['delete']
            self.assertEqual(expected, mock_notify.call_args_list)
