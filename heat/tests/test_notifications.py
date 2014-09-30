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
from oslo.utils import timeutils

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
# imports for mocking
from heat.engine.resources import autoscaling
from heat.engine.resources import instance
from heat.engine.resources import loadbalancer
from heat.engine.resources import nova_keypair
from heat.engine.resources import user
from heat.engine.resources import wait_condition as waitc
from heat.engine import signal_responder as signal
from heat.engine import stack_resource
from heat.tests import common
from heat.tests import generic_resource
# reuse the same template than autoscaling tests
from heat.tests.test_autoscaling import as_template
from heat.tests import utils


class NotificationTest(common.HeatTestCase):

    def setUp(self):
        super(NotificationTest, self).setUp()
        resource._register_class('GenericResource',
                                 generic_resource.ResourceWithProps)

    def create_test_stack(self):
        test_template = {'HeatTemplateFormatVersion': '2012-12-12',
                         'Parameters': {'Foo': {'Type': 'String'},
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
                      'orchestration.stack.%s.start' % action,
                      {'state_reason': 'Stack %s started' % action.upper(),
                       'user_id': 'test_username',
                       'stack_identity': stack_arn,
                       'tenant_id': 'test_tenant',
                       'create_at': self.create_at,
                       'stack_name': self.stack_name,
                       'state': '%s_IN_PROGRESS' % action.upper()}),
            mock.call(self.ctx,
                      'orchestration.stack.%s.end' % action,
                      {'state_reason':
                       'Stack %s completed successfully' % action.upper(),
                       'user_id': 'test_username',
                       'stack_identity': stack_arn,
                       'tenant_id': 'test_tenant',
                       'create_at': self.create_at,
                       'stack_name': self.stack_name,
                       'state': '%s_COMPLETE' % action.upper()})]

    @mock.patch('oslo.messaging.notify.notifier.Notifier.info')
    def test_create_stack(self, mock_notify):
        self.create_test_stack()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(self.expected['create'],
                         mock_notify.call_args_list)

    @mock.patch('oslo.messaging.notify.notifier.Notifier.info')
    def test_create_and_suspend_stack(self, mock_notify):
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

    @mock.patch('oslo.messaging.notify.notifier.Notifier.info')
    def test_create_and_delete_stack(self, mock_notify):
        self.create_test_stack()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(self.expected['create'],
                         mock_notify.call_args_list)
        self.stack.delete()
        self.assertEqual((self.stack.DELETE, self.stack.COMPLETE),
                         self.stack.state)
        expected = self.expected['create'] + self.expected['delete']

        self.assertEqual(expected, mock_notify.call_args_list)


class ScaleNotificationTest(common.HeatTestCase):

    def setUp(self):
        super(ScaleNotificationTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.ctx.tenant_id = 'test_tenant'

    def create_autoscaling_stack_and_get_group(self):

        env = environment.Environment()
        env.load({u'parameters':
                  {u'KeyName': 'foo', 'ImageId': 'cloudimage'}})
        t = template_format.parse(as_template)
        template = parser.Template(t)
        self.stack_name = utils.random_name()
        stack = parser.Stack(self.ctx, self.stack_name, template,
                             env=env, disable_rollback=True)
        stack.store()
        self.created_time = stack.created_time
        self.create_at = timeutils.isotime(self.created_time)
        stack.create()
        self.stack = stack
        group = stack['WebServerGroup']
        self.assertEqual((group.CREATE, group.COMPLETE), group.state)
        return group

    def mock_stack_except_for_group(self):
        self.m_validate = self.patchobject(parser.Stack, 'validate')
        self.patchobject(nova_keypair.KeypairConstraint, 'validate')
        self.patchobject(glance.ImageConstraint, 'validate')
        self.patchobject(instance.Instance, 'handle_create')\
            .return_value = True
        self.patchobject(instance.Instance, 'check_create_complete')\
            .return_value = True
        self.patchobject(stack_resource.StackResource,
                         'check_update_complete').return_value = True

        self.patchobject(loadbalancer.LoadBalancer, 'handle_update')
        self.patchobject(user.User, 'handle_create')
        self.patchobject(user.AccessKey, 'handle_create')
        self.patchobject(waitc.WaitCondition, 'handle_create')
        self.patchobject(signal.SignalResponder, 'handle_create')

    def expected_notifs_calls(self, group, adjust,
                              start_capacity, end_capacity=None,
                              with_error=None):

        stack_arn = self.stack.identifier().arn()
        expected = [mock.call(self.ctx,
                    'orchestration.autoscaling.start',
                    {'state_reason':
                     'Stack CREATE completed successfully',
                     'user_id': 'test_username',
                     'stack_identity': stack_arn,
                     'tenant_id': 'test_tenant',
                     'create_at': self.create_at,
                     'adjustment_type': 'ChangeInCapacity',
                     'groupname': group.FnGetRefId(),
                     'capacity': start_capacity,
                     'adjustment': adjust,
                     'stack_name': self.stack_name,
                     'message': 'Start resizing the group %s' %
                     group.FnGetRefId(),
                     'state': 'CREATE_COMPLETE'})
                    ]
        if with_error:
            expected += [mock.call(self.ctx,
                         'orchestration.autoscaling.error',
                         {'state_reason':
                          'Stack CREATE completed successfully',
                          'user_id': 'test_username',
                          'stack_identity': stack_arn,
                          'tenant_id': 'test_tenant',
                          'create_at': self.create_at,
                          'adjustment_type': 'ChangeInCapacity',
                          'groupname': group.FnGetRefId(),
                          'capacity': start_capacity,
                          'adjustment': adjust,
                          'stack_name': self.stack_name,
                          'message': with_error,
                          'state': 'CREATE_COMPLETE'})
                         ]
        else:
            expected += [mock.call(self.ctx,
                         'orchestration.autoscaling.end',
                         {'state_reason':
                          'Stack CREATE completed successfully',
                          'user_id': 'test_username',
                          'stack_identity': stack_arn,
                          'tenant_id': 'test_tenant',
                          'create_at': self.create_at,
                          'adjustment_type': 'ChangeInCapacity',
                          'groupname': group.FnGetRefId(),
                          'capacity': end_capacity,
                          'adjustment': adjust,
                          'stack_name': self.stack_name,
                          'message': 'End resizing the group %s' %
                          group.FnGetRefId(),
                          'state': 'CREATE_COMPLETE'})
                         ]

        return expected

    @mock.patch('heat.engine.notification.stack.send')
    @mock.patch('oslo.messaging.notify.notifier.Notifier.info')
    def test_scale_success(self, mock_notify, mock_send):
        self.mock_stack_except_for_group()
        group = self.create_autoscaling_stack_and_get_group()
        expected = self.expected_notifs_calls(group,
                                              adjust=1,
                                              start_capacity=1,
                                              end_capacity=2,
                                              )
        group.adjust(1)
        self.assertEqual(2, len(group.get_instance_names()))
        mock_notify.assert_has_calls(expected)

        expected = self.expected_notifs_calls(group,
                                              adjust=-1,
                                              start_capacity=2,
                                              end_capacity=1,
                                              )
        group.adjust(-1)
        self.assertEqual(1, len(group.get_instance_names()))
        mock_notify.assert_has_calls(expected)

    @mock.patch('heat.engine.notification.stack.send')
    @mock.patch('oslo.messaging.notify.notifier.Notifier.info')
    @mock.patch('oslo.messaging.notify.notifier.Notifier.error')
    def test_scaleup_failure(self, mock_error, mock_info, mock_send):
        self.mock_stack_except_for_group()
        group = self.create_autoscaling_stack_and_get_group()

        err_message = 'Boooom'
        m_as = self.patchobject(autoscaling.AutoScalingGroup, 'resize')
        m_as.side_effect = exception.Error(err_message)

        info, error = self.expected_notifs_calls(group,
                                                 adjust=2,
                                                 start_capacity=1,
                                                 with_error=err_message)
        self.assertRaises(exception.Error, group.adjust, 2)
        self.assertEqual(1, len(group.get_instance_names()))
        mock_error.assert_has_calls([error])
        mock_info.assert_has_calls([info])
