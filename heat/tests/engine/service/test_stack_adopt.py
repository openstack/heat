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
from oslo_config import cfg
from oslo_messaging.rpc import dispatcher
import six

from heat.common import exception
from heat.engine import service
from heat.engine import stack as parser
from heat.objects import stack as stack_object
from heat.tests import common
from heat.tests import utils


class StackServiceAdoptTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceAdoptTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.thread_group_mgr = service.ThreadGroupManager()

    def _get_adopt_data_and_template(self, environment=None):
        template = {
            "heat_template_version": "2013-05-23",
            "parameters": {"app_dbx": {"type": "string"}},
            "resources": {"res1": {"type": "GenericResourceType"}}}

        adopt_data = {
            "status": "COMPLETE",
            "name": "rtrove1",
            "environment": environment,
            "template": template,
            "action": "CREATE",
            "id": "8532f0d3-ea84-444e-b2bb-2543bb1496a4",
            "resources": {"res1": {
                    "status": "COMPLETE",
                    "name": "database_password",
                    "resource_id": "yBpuUROjfGQ2gKOD",
                    "action": "CREATE",
                    "type": "GenericResourceType",
                    "metadata": {}}}}
        return template, adopt_data

    def _do_adopt(self, stack_name, template, input_params, adopt_data):
        result = self.man.create_stack(self.ctx, stack_name,
                                       template, input_params, None,
                                       {'adopt_stack_data': str(adopt_data)})
        self.man.thread_group_mgr.stop(result['stack_id'], graceful=True)
        return result

    def test_stack_adopt_with_params(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        cfg.CONF.set_override('convergence_engine', False)
        env = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_adopt_data_and_template(env)
        result = self._do_adopt("test_adopt_with_params", template, {},
                                adopt_data)

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(env['parameters'],
                         stack.raw_template.environment['parameters'])

    @mock.patch.object(parser.Stack, '_converge_create_or_update')
    @mock.patch.object(parser.Stack, '_send_notification_and_add_event')
    def test_convergence_stack_adopt_with_params(self,
                                                 mock_converge,
                                                 mock_send_notif):
        cfg.CONF.set_override('enable_stack_adopt', True)
        cfg.CONF.set_override('convergence_engine', True)
        env = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_adopt_data_and_template(env)
        result = self._do_adopt("test_adopt_with_params", template, {},
                                adopt_data)

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(env['parameters'],
                         stack.raw_template.environment['parameters'])
        self.assertTrue(mock_converge.called)

    def test_stack_adopt_saves_input_params(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        cfg.CONF.set_override('convergence_engine', False)
        env = {'parameters': {"app_dbx": "foo"}}
        input_params = {
            "parameters": {"app_dbx": "bar"}
        }
        template, adopt_data = self._get_adopt_data_and_template(env)
        result = self._do_adopt("test_adopt_saves_inputs", template,
                                input_params, adopt_data)

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(input_params['parameters'],
                         stack.raw_template.environment['parameters'])

    @mock.patch.object(parser.Stack, '_converge_create_or_update')
    @mock.patch.object(parser.Stack, '_send_notification_and_add_event')
    def test_convergence_stack_adopt_saves_input_params(
            self, mock_converge, mock_send_notif):
        cfg.CONF.set_override('enable_stack_adopt', True)
        cfg.CONF.set_override('convergence_engine', True)
        env = {'parameters': {"app_dbx": "foo"}}
        input_params = {
            "parameters": {"app_dbx": "bar"}
        }
        template, adopt_data = self._get_adopt_data_and_template(env)
        result = self._do_adopt("test_adopt_saves_inputs", template,
                                input_params, adopt_data)

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual(template, stack.raw_template.template)
        self.assertEqual(input_params['parameters'],
                         stack.raw_template.environment['parameters'])
        self.assertTrue(mock_converge.called)

    def test_stack_adopt_stack_state(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        cfg.CONF.set_override('convergence_engine', False)
        env = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_adopt_data_and_template(env)
        result = self._do_adopt("test_adopt_stack_state", template, {},
                                adopt_data)

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual((parser.Stack.ADOPT, parser.Stack.COMPLETE),
                         (stack.action, stack.status))

    @mock.patch.object(parser.Stack, '_converge_create_or_update')
    @mock.patch.object(parser.Stack, '_send_notification_and_add_event')
    def test_convergence_stack_adopt_stack_state(self, mock_converge,
                                                 mock_send_notif):
        cfg.CONF.set_override('enable_stack_adopt', True)
        cfg.CONF.set_override('convergence_engine', True)
        env = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_adopt_data_and_template(env)
        result = self._do_adopt("test_adopt_stack_state", template, {},
                                adopt_data)

        stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertEqual((parser.Stack.ADOPT, parser.Stack.IN_PROGRESS),
                         (stack.action, stack.status))
        self.assertTrue(mock_converge.called)

    def test_stack_adopt_disabled(self):
        # to test disable stack adopt
        cfg.CONF.set_override('enable_stack_adopt', False)
        env = {'parameters': {"app_dbx": "test"}}
        template, adopt_data = self._get_adopt_data_and_template(env)
        ex = self.assertRaises(
            dispatcher.ExpectedException,
            self.man.create_stack,
            self.ctx, "test_adopt_stack_disabled",
            template, {}, None,
            {'adopt_stack_data': str(adopt_data)})
        self.assertEqual(exception.NotSupported, ex.exc_info[0])
        self.assertIn('Stack Adopt', six.text_type(ex.exc_info[1]))
