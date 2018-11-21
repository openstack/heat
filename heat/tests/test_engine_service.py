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

import uuid

import mock
from oslo_config import cfg
from oslo_messaging.rpc import dispatcher
from oslo_serialization import jsonutils as json
import six

from heat.common import context
from heat.common import environment_util as env_util
from heat.common import exception
from heat.common import identifier
from heat.common import policy
from heat.common import template_format
from heat.engine.cfn import template as cfntemplate
from heat.engine import environment
from heat.engine.hot import functions as hot_functions
from heat.engine.hot import template as hottemplate
from heat.engine import resource as res
from heat.engine import service
from heat.engine import stack as parser
from heat.engine import template as templatem
from heat.objects import stack as stack_object
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import generic_resource as generic_rsrc
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')
cfg.CONF.import_opt('enable_stack_abandon', 'heat.common.config')

wp_template_no_default = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''

user_policy_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a User",
  "Parameters" : {},
  "Resources" : {
    "CfnUser" : {
      "Type" : "AWS::IAM::User",
      "Properties" : {
        "Policies" : [ { "Ref": "WebServerAccessPolicy"} ]
      }
    },
    "WebServerAccessPolicy" : {
      "Type" : "OS::Heat::AccessPolicy",
      "Properties" : {
        "AllowedResources" : [ "WebServer" ]
      }
    },
    "HostKeys" : {
      "Type" : "AWS::IAM::AccessKey",
      "Properties" : {
        "UserName" : {"Ref": "CfnUser"}
      }
    },
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''

server_config_template = '''
heat_template_version: 2013-05-23
resources:
  WebServer:
    type: OS::Nova::Server
'''


class StackCreateTest(common.HeatTestCase):
    def test_wordpress_single_instance_stack_create(self):
        stack = tools.get_stack('test_stack', utils.dummy_context())
        fc = tools.setup_mocks_with_mock(self, stack)
        stack.store()
        stack.create()

        self.assertIsNotNone(stack['WebServer'])
        self.assertGreater(int(stack['WebServer'].resource_id), 0)
        self.assertNotEqual(stack['WebServer'].ipaddress, '0.0.0.0')
        tools.validate_setup_mocks_with_mock(stack, fc)

    def test_wordpress_single_instance_stack_adopt(self):
        t = template_format.parse(tools.wp_template)
        template = templatem.Template(t)
        ctx = utils.dummy_context()
        adopt_data = {
            'resources': {
                'WebServer': {
                    'resource_id': 'test-res-id'
                }
            }
        }
        stack = parser.Stack(ctx,
                             'test_stack',
                             template,
                             adopt_stack_data=adopt_data)

        fc = tools.setup_mocks_with_mock(self, stack,
                                         mock_image_constraint=False)
        stack.store()
        stack.adopt()

        self.assertIsNotNone(stack['WebServer'])
        self.assertEqual('test-res-id', stack['WebServer'].resource_id)
        self.assertEqual((stack.ADOPT, stack.COMPLETE), stack.state)
        tools.validate_setup_mocks_with_mock(
            stack, fc, mock_image_constraint=False, validate_create=False)

    def test_wordpress_single_instance_stack_adopt_fail(self):
        t = template_format.parse(tools.wp_template)
        template = templatem.Template(t)
        ctx = utils.dummy_context()
        adopt_data = {
            'resources': {
                'WebServer1': {
                    'resource_id': 'test-res-id'
                }
            }
        }
        stack = parser.Stack(ctx,
                             'test_stack',
                             template,
                             adopt_stack_data=adopt_data)

        fc = tools.setup_mocks_with_mock(self, stack,
                                         mock_image_constraint=False)
        stack.store()
        stack.adopt()
        self.assertIsNotNone(stack['WebServer'])
        expected = ('Resource ADOPT failed: Exception: resources.WebServer: '
                    'Resource ID was not provided.')
        self.assertEqual(expected, stack.status_reason)
        self.assertEqual((stack.ADOPT, stack.FAILED), stack.state)
        tools.validate_setup_mocks_with_mock(
            stack, fc, mock_image_constraint=False, validate_create=False)

    def test_wordpress_single_instance_stack_delete(self):
        ctx = utils.dummy_context()
        stack = tools.get_stack('test_stack', ctx)
        fc = tools.setup_mocks_with_mock(self, stack, mock_keystone=False)
        stack_id = stack.store()
        stack.create()

        db_s = stack_object.Stack.get_by_id(ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.assertIsNotNone(stack['WebServer'])
        self.assertGreater(int(stack['WebServer'].resource_id), 0)

        self.patchobject(fc.servers, 'delete',
                         side_effect=fakes_nova.fake_exception())
        stack.delete()

        rsrc = stack['WebServer']
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual((stack.DELETE, stack.COMPLETE), rsrc.state)
        self.assertIsNone(stack_object.Stack.get_by_id(ctx, stack_id))

        db_s.refresh()
        self.assertEqual('DELETE', db_s.action)
        self.assertEqual('COMPLETE', db_s.status)
        tools.validate_setup_mocks_with_mock(stack, fc)


class StackConvergenceServiceCreateUpdateTest(common.HeatTestCase):

    def setUp(self):
        super(StackConvergenceServiceCreateUpdateTest, self).setUp()
        cfg.CONF.set_override('convergence_engine', True)
        self.ctx = utils.dummy_context()
        self.man = service.EngineService('a-host', 'a-topic')
        self.man.thread_group_mgr = tools.DummyThreadGroupManager()

    def _stub_update_mocks(self, stack_to_return):
        self.patchobject(parser, 'Stack')
        parser.Stack.load.return_value = stack_to_return

        self.patchobject(templatem, 'Template')
        self.patchobject(environment, 'Environment')

    def _test_stack_create_convergence(self, stack_name):
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'

        stack = tools.get_stack(stack_name, self.ctx,
                                template=tools.string_template_five,
                                convergence=True)

        stack.converge = None
        self.patchobject(templatem, 'Template', return_value=stack.t)
        self.patchobject(environment, 'Environment', return_value=stack.env)
        self.patchobject(parser, 'Stack', return_value=stack)
        self.patchobject(stack, 'validate', return_value=None)

        api_args = {'timeout_mins': 60, 'disable_rollback': False}
        result = self.man.create_stack(self.ctx, 'service_create_test_stack',
                                       template, params, None, api_args)
        db_stack = stack_object.Stack.get_by_id(self.ctx, result['stack_id'])
        self.assertTrue(db_stack.convergence)
        self.assertEqual(result['stack_id'], db_stack.id)
        templatem.Template.assert_called_once_with(template, files=None)
        environment.Environment.assert_called_once_with(params)
        parser.Stack.assert_called_once_with(
            self.ctx, stack.name,
            stack.t, owner_id=None,
            parent_resource=None,
            nested_depth=0, user_creds_id=None,
            stack_user_project_id=None,
            timeout_mins=60,
            disable_rollback=False,
            convergence=True)

    def test_stack_create_enabled_convergence_engine(self):
        stack_name = 'service_create_test_stack'
        self._test_stack_create_convergence(stack_name)

    def test_stack_update_enabled_convergence_engine(self):
        stack_name = 'service_update_test_stack'
        params = {'foo': 'bar'}
        template = '{ "Template": "data" }'
        old_stack = tools.get_stack(stack_name, self.ctx,
                                    template=tools.string_template_five,
                                    convergence=True)
        old_stack.timeout_mins = 1
        old_stack.store()
        stack = tools.get_stack(stack_name, self.ctx,
                                template=tools.string_template_five_update,
                                convergence=True)

        self._stub_update_mocks(old_stack)

        templatem.Template.return_value = stack.t
        environment.Environment.return_value = stack.env
        parser.Stack.return_value = stack

        self.patchobject(stack, 'validate', return_value=None)

        api_args = {'timeout_mins': 60, 'disable_rollback': False,
                    rpc_api.PARAM_CONVERGE: False}
        result = self.man.update_stack(self.ctx, old_stack.identifier(),
                                       template, params, None, api_args)
        self.assertTrue(old_stack.convergence)
        self.assertEqual(old_stack.identifier(), result)
        self.assertIsInstance(result, dict)
        self.assertTrue(result['stack_id'])
        parser.Stack.load.assert_called_once_with(
            self.ctx, stack=mock.ANY)
        templatem.Template.assert_called_once_with(template, files=None)
        environment.Environment.assert_called_once_with(params)


class StackServiceAuthorizeTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceAuthorizeTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.engine_id = 'engine-fake-uuid'

    @tools.stack_context('service_authorize_stack_user_nocreds_test_stack')
    def test_stack_authorize_stack_user_nocreds(self):
        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))

    @tools.stack_context('service_authorize_user_attribute_error_test_stack')
    def test_stack_authorize_stack_user_attribute_error(self):
        self.patchobject(json, 'loads', side_effect=AttributeError)
        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))
        json.loads.assert_called_once_with(None)

    @tools.stack_context('service_authorize_stack_user_type_error_test_stack')
    def test_stack_authorize_stack_user_type_error(self):
        self.patchobject(json, 'loads', side_effect=TypeError)
        self.assertFalse(self.eng._authorize_stack_user(self.ctx,
                                                        self.stack,
                                                        'foo'))
        json.loads.assert_called_once_with(None)

    def test_stack_authorize_stack_user(self):
        self.ctx = utils.dummy_context()
        self.ctx.aws_creds = '{"ec2Credentials": {"access": "4567"}}'
        stack_name = 'stack_authorize_stack_user'
        stack = tools.get_stack(stack_name, self.ctx, user_policy_template)
        self.stack = stack
        fc = tools.setup_mocks_with_mock(self, stack)
        self.patchobject(fc.servers, 'delete',
                         side_effect=fakes_nova.fake_exception())

        stack.store()
        stack.create()

        self.assertTrue(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))

        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'CfnUser'))

        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'NoSuchResource'))
        tools.validate_setup_mocks_with_mock(stack, fc)

    def test_stack_authorize_stack_user_user_id(self):
        self.ctx = utils.dummy_context(user_id=str(uuid.uuid4()))
        stack_name = 'stack_authorize_stack_user_user_id'
        stack = tools.get_stack(stack_name, self.ctx, server_config_template)
        self.stack = stack

        def handler(resource_name):
            return resource_name == 'WebServer'

        self.stack.register_access_allowed_handler(self.ctx.user_id, handler)

        # matching credential_id and resource_name
        self.assertTrue(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))

        # not matching resource_name
        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'NoSuchResource'))

        # not matching credential_id
        self.ctx.user = str(uuid.uuid4())
        self.assertFalse(self.eng._authorize_stack_user(
            self.ctx, self.stack, 'WebServer'))


class StackServiceTest(common.HeatTestCase):

    def setUp(self):
        super(StackServiceTest, self).setUp()

        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.thread_group_mgr = tools.DummyThreadGroupManager()
        self.eng.engine_id = 'engine-fake-uuid'

    @tools.stack_context('service_identify_test_stack', False)
    def test_stack_identify(self):
        identity = self.eng.identify_stack(self.ctx, self.stack.name)
        self.assertEqual(self.stack.identifier(), identity)

    @tools.stack_context('ef0c41a4-644f-447c-ad80-7eecb0becf79', False)
    def test_stack_identify_by_name_in_uuid(self):
        identity = self.eng.identify_stack(self.ctx, self.stack.name)
        self.assertEqual(self.stack.identifier(), identity)

    @tools.stack_context('service_identify_uuid_test_stack', False)
    def test_stack_identify_uuid(self):
        identity = self.eng.identify_stack(self.ctx, self.stack.id)
        self.assertEqual(self.stack.identifier(), identity)

    def test_stack_identify_nonexist(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.identify_stack, self.ctx, 'wibble')
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])

    @tools.stack_context('service_create_existing_test_stack', False)
    def test_stack_create_existing(self):
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.create_stack, self.ctx,
                               self.stack.name, self.stack.t.t, {}, None, {})
        self.assertEqual(exception.StackExists, ex.exc_info[0])

    @tools.stack_context('service_name_tenants_test_stack', False)
    def test_stack_by_name_tenants(self):
        self.assertEqual(
            self.stack.id,
            stack_object.Stack.get_by_name(self.ctx, self.stack.name).id
        )
        ctx2 = utils.dummy_context(tenant_id='stack_service_test_tenant2')
        self.assertIsNone(stack_object.Stack.get_by_name(
            ctx2,
            self.stack.name))

    @tools.stack_context('service_badname_test_stack', False)
    def test_stack_by_name_badname(self):
        # If a bad name type, such as a map, is passed, we should just return
        # None, as it's converted to a string, which won't match any name
        ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.assertIsNone(stack_object.Stack.get_by_name(
            ctx,
            {'notallowed': self.stack.name}))
        self.assertIsNone(stack_object.Stack.get_by_name_and_owner_id(
            ctx,
            {'notallowed': self.stack.name}, 'owner'))

    @tools.stack_context('service_list_all_test_stack')
    def test_stack_list_all(self):
        sl = self.eng.list_stacks(self.ctx)

        self.assertEqual(1, len(sl))
        for s in sl:
            self.assertIn('creation_time', s)
            self.assertIn('updated_time', s)
            self.assertIn('deletion_time', s)
            self.assertIsNone(s['deletion_time'])
            self.assertIn('stack_identity', s)
            self.assertIsNotNone(s['stack_identity'])
            self.assertIn('stack_name', s)
            self.assertEqual(self.stack.name, s['stack_name'])
            self.assertIn('stack_status', s)
            self.assertIn('stack_status_reason', s)
            self.assertIn('description', s)
            self.assertEqual('', s['description'])

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_marker_info(self, mock_stack_get_all):
        limit = object()
        marker = object()
        sort_keys = object()
        sort_dir = object()
        self.eng.list_stacks(self.ctx, limit=limit, marker=marker,
                             sort_keys=sort_keys, sort_dir=sort_dir)
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=limit,
                                                   sort_keys=sort_keys,
                                                   marker=marker,
                                                   sort_dir=sort_dir,
                                                   filters=mock.ANY,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_filtering_info(self, mock_stack_get_all):
        filters = {'foo': 'bar'}
        self.eng.list_stacks(self.ctx, filters=filters)
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=filters,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_passes_filter_translated(self, mock_stack_get_all):
        filters = {'stack_name': 'bar'}
        self.eng.list_stacks(self.ctx, filters=filters)
        translated = {'name': 'bar'}
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=translated,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_nested(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_nested=True)
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=mock.ANY,
                                                   show_deleted=mock.ANY,
                                                   show_nested=True,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_deleted(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_deleted=True)
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=mock.ANY,
                                                   show_deleted=True,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_show_hidden(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, show_hidden=True)
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=mock.ANY,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=True,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_tags(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, tags=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=mock.ANY,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=['foo', 'bar'],
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_tags_any(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, tags_any=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=mock.ANY,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=['foo', 'bar'],
                                                   not_tags=mock.ANY,
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_not_tags(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, not_tags=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=mock.ANY,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=['foo', 'bar'],
                                                   not_tags_any=mock.ANY)

    @mock.patch.object(stack_object.Stack, 'get_all')
    def test_stack_list_not_tags_any(self, mock_stack_get_all):
        self.eng.list_stacks(self.ctx, not_tags_any=['foo', 'bar'])
        mock_stack_get_all.assert_called_once_with(self.ctx,
                                                   limit=mock.ANY,
                                                   sort_keys=mock.ANY,
                                                   marker=mock.ANY,
                                                   sort_dir=mock.ANY,
                                                   filters=mock.ANY,
                                                   show_deleted=mock.ANY,
                                                   show_nested=mock.ANY,
                                                   show_hidden=mock.ANY,
                                                   tags=mock.ANY,
                                                   tags_any=mock.ANY,
                                                   not_tags=mock.ANY,
                                                   not_tags_any=['foo', 'bar'])

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_passes_filter_info(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, filters={'foo': 'bar'})
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters={'foo': 'bar'},
                                                     show_deleted=False,
                                                     show_nested=False,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stacks_show_nested(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_nested=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     show_deleted=False,
                                                     show_nested=True,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stack_show_deleted(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_deleted=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     show_deleted=True,
                                                     show_nested=False,
                                                     show_hidden=False,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_count_stack_show_hidden(self, mock_stack_count_all):
        self.eng.count_stacks(self.ctx, show_hidden=True)
        mock_stack_count_all.assert_called_once_with(mock.ANY,
                                                     filters=mock.ANY,
                                                     show_deleted=False,
                                                     show_nested=False,
                                                     show_hidden=True,
                                                     tags=None,
                                                     tags_any=None,
                                                     not_tags=None,
                                                     not_tags_any=None)

    @tools.stack_context('service_export_stack')
    def test_export_stack(self):
        cfg.CONF.set_override('enable_stack_abandon', True)
        self.patchobject(parser.Stack, 'load', return_value=self.stack)
        expected_res = {
            u'WebServer': {
                'action': 'CREATE',
                'metadata': {},
                'name': u'WebServer',
                'resource_data': {},
                'resource_id': '9999',
                'status': 'COMPLETE',
                'type': u'AWS::EC2::Instance'}}
        self.stack.tags = ['tag1', 'tag2']
        ret = self.eng.export_stack(self.ctx, self.stack.identifier())
        self.assertEqual(11, len(ret))
        self.assertEqual('CREATE', ret['action'])
        self.assertEqual('COMPLETE', ret['status'])
        self.assertEqual('service_export_stack', ret['name'])
        self.assertEqual({}, ret['files'])
        self.assertIn('id', ret)
        self.assertEqual(expected_res, ret['resources'])
        self.assertEqual(self.stack.t.t, ret['template'])
        self.assertIn('project_id', ret)
        self.assertIn('stack_user_project_id', ret)
        self.assertIn('environment', ret)
        self.assertIn('files', ret)
        self.assertEqual(['tag1', 'tag2'], ret['tags'])

    @tools.stack_context('service_abandon_stack')
    def test_abandon_stack(self):
        cfg.CONF.set_override('enable_stack_abandon', True)
        self.patchobject(parser.Stack, 'load', return_value=self.stack)
        self.eng.abandon_stack(self.ctx, self.stack.identifier())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_stack,
                               self.ctx, self.stack.identifier(),
                               resolve_outputs=True)
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])

    def test_stack_describe_nonexistent(self):
        non_exist_identifier = identifier.HeatIdentifier(
            self.ctx.tenant_id, 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        stack_not_found_exc = exception.EntityNotFound(
            entity='Stack', name='test')
        self.patchobject(service.EngineService, '_get_stack',
                         side_effect=stack_not_found_exc)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier,
                               resolve_outputs=True)
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])
        service.EngineService._get_stack.assert_called_once_with(
            self.ctx, non_exist_identifier,
            show_deleted=True)

    def test_stack_describe_bad_tenant(self):
        non_exist_identifier = identifier.HeatIdentifier(
            'wibble', 'wibble',
            '18d06e2e-44d3-4bef-9fbf-52480d604b02')

        invalid_tenant_exc = exception.InvalidTenant(target='test',
                                                     actual='test')
        self.patchobject(service.EngineService, '_get_stack',
                         side_effect=invalid_tenant_exc)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_stack,
                               self.ctx, non_exist_identifier,
                               resolve_outputs=True)
        self.assertEqual(exception.InvalidTenant, ex.exc_info[0])
        service.EngineService._get_stack.assert_called_once_with(
            self.ctx, non_exist_identifier,
            show_deleted=True)

    @tools.stack_context('service_describe_test_stack', False)
    def test_stack_describe(self):
        s = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.patchobject(service.EngineService, '_get_stack', return_value=s)

        sl = self.eng.show_stack(self.ctx, self.stack.identifier(),
                                 resolve_outputs=True)

        self.assertEqual(1, len(sl))

        s = sl[0]
        self.assertIn('creation_time', s)
        self.assertIn('updated_time', s)
        self.assertIn('deletion_time', s)
        self.assertIsNone(s['deletion_time'])
        self.assertIn('stack_identity', s)
        self.assertIsNotNone(s['stack_identity'])
        self.assertIn('stack_name', s)
        self.assertEqual(self.stack.name, s['stack_name'])
        self.assertIn('stack_status', s)
        self.assertIn('stack_status_reason', s)
        self.assertIn('description', s)
        self.assertIn('WordPress', s['description'])
        self.assertIn('parameters', s)
        service.EngineService._get_stack.assert_called_once_with(
            self.ctx,
            self.stack.identifier(),
            show_deleted=True)

    @tools.stack_context('service_describe_all_test_stack', False)
    def test_stack_describe_all(self):
        sl = self.eng.show_stack(self.ctx, None, resolve_outputs=True)

        self.assertEqual(1, len(sl))

        s = sl[0]
        self.assertIn('creation_time', s)
        self.assertIn('updated_time', s)
        self.assertIn('deletion_time', s)
        self.assertIsNone(s['deletion_time'])
        self.assertIn('stack_identity', s)
        self.assertIsNotNone(s['stack_identity'])
        self.assertIn('stack_name', s)
        self.assertEqual(self.stack.name, s['stack_name'])
        self.assertIn('stack_status', s)
        self.assertIn('stack_status_reason', s)
        self.assertIn('description', s)
        self.assertIn('WordPress', s['description'])
        self.assertIn('parameters', s)

    @mock.patch('heat.engine.template._get_template_extension_manager')
    def test_list_template_versions(self, templ_mock):

        class DummyMgr(object):
            def names(self):
                return ['a.2012-12-12', 'c.newton', 'c.2016-10-14',
                        'c.something']

            def __getitem__(self, item):
                m = mock.MagicMock()
                if item == 'a.2012-12-12':
                    m.plugin = cfntemplate.CfnTemplate
                    return m
                else:
                    m.plugin = hottemplate.HOTemplate20130523
                    return m

        templ_mock.return_value = DummyMgr()
        templates = self.eng.list_template_versions(self.ctx)
        expected = [{'version': 'a.2012-12-12', 'type': 'cfn', 'aliases': []},
                    {'version': 'c.2016-10-14',
                     'aliases': ['c.newton', 'c.something'], 'type': 'hot'}]
        self.assertEqual(expected, templates)

    @mock.patch('heat.engine.template._get_template_extension_manager')
    def test_list_template_versions_invalid_version(self, templ_mock):

        class DummyMgr(object):
            def names(self):
                return ['c.something']

            def __getitem__(self, item):
                m = mock.MagicMock()
                if item == 'c.something':
                    m.plugin = cfntemplate.CfnTemplate
                    return m

        templ_mock.return_value = DummyMgr()
        ret = self.assertRaises(exception.InvalidTemplateVersions,
                                self.eng.list_template_versions, self.ctx)
        self.assertIn('A template version alias c.something was added',
                      six.text_type(ret))

    @mock.patch('heat.engine.template._get_template_extension_manager')
    def test_list_template_functions(self, templ_mock):

        class DummyFunc1(object):
            """Dummy Func1.

            Dummy Func1 Long Description.
            """

        class DummyFunc2(object):
            """Dummy Func2.

            Dummy Func2 Long Description.
            """

        class DummyConditionFunc(object):
            """Dummy Condition Func.

            Dummy Condition Func Long Description.
            """

        plugin_mock = mock.Mock(
            functions={'dummy1': DummyFunc1,
                       'dummy2': DummyFunc2,
                       'removed': hot_functions.Removed},
            condition_functions={'condition_dummy': DummyConditionFunc})
        dummy_tmpl = mock.Mock(plugin=plugin_mock)

        class DummyMgr(object):
            def __getitem__(self, item):
                return dummy_tmpl

        templ_mock.return_value = DummyMgr()
        functions = self.eng.list_template_functions(self.ctx, 'dummytemplate')
        expected = [{'functions': 'dummy1',
                     'description': 'Dummy Func1.'},
                    {'functions': 'dummy2',
                     'description': 'Dummy Func2.'}]
        self.assertEqual(sorted(expected, key=lambda k: k['functions']),
                         sorted(functions, key=lambda k: k['functions']))

        # test with_condition
        functions = self.eng.list_template_functions(self.ctx, 'dummytemplate',
                                                     with_condition=True)
        expected = [{'functions': 'dummy1',
                     'description': 'Dummy Func1.'},
                    {'functions': 'dummy2',
                     'description': 'Dummy Func2.'},
                    {'functions': 'condition_dummy',
                     'description': 'Dummy Condition Func.'}]
        self.assertEqual(sorted(expected, key=lambda k: k['functions']),
                         sorted(functions, key=lambda k: k['functions']))

    @mock.patch('heat.engine.template._get_template_extension_manager')
    def test_list_template_functions_version_not_found(self, templ_mock):
        class DummyMgr(object):
            def __getitem__(self, item):
                raise KeyError()

        templ_mock.return_value = DummyMgr()
        version = 'dummytemplate'
        ex = self.assertRaises(exception.NotFound,
                               self.eng.list_template_functions,
                               self.ctx,
                               version)
        msg = "Template with version %s not found" % version
        self.assertEqual(msg, six.text_type(ex))

    def test_stack_list_outputs(self):
        t = template_format.parse(tools.wp_template)
        t['outputs'] = {
            'test': {'value': '{ get_attr: fir }',
                     'description': 'sec'},
            'test2': {'value': 'sec'}}
        tmpl = templatem.Template(t)
        stack = parser.Stack(self.ctx, 'service_list_outputs_stack', tmpl)

        self.patchobject(self.eng, '_get_stack')
        self.patchobject(parser.Stack, 'load', return_value=stack)

        outputs = self.eng.list_outputs(self.ctx, mock.ANY)

        self.assertIn({'output_key': 'test',
                       'description': 'sec'}, outputs)
        self.assertIn({'output_key': 'test2',
                       'description': 'No description given'},
                      outputs)

    def test_stack_empty_list_outputs(self):
        # Ensure that stack with no output returns empty list
        t = template_format.parse(tools.wp_template)
        t['outputs'] = {}
        tmpl = templatem.Template(t)
        stack = parser.Stack(self.ctx, 'service_list_outputs_stack', tmpl)

        self.patchobject(self.eng, '_get_stack')
        self.patchobject(parser.Stack, 'load', return_value=stack)

        outputs = self.eng.list_outputs(self.ctx, mock.ANY)
        self.assertEqual([], outputs)

    def test_stack_delete_complete_is_not_found(self):
        t = template_format.parse(tools.wp_template)
        tmpl = templatem.Template(t)
        stack = parser.Stack(self.ctx, 'delete_complete_stack', tmpl)
        self.patchobject(self.eng, '_get_stack')
        self.patchobject(parser.Stack, 'load', return_value=stack)
        stack.status = stack.COMPLETE
        stack.action = stack.DELETE
        stack.convergence = True
        self.eng.thread_group_mgr.start = mock.MagicMock()
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.delete_stack,
                               'irrelevant',
                               'irrelevant')
        self.assertEqual(exception.EntityNotFound, ex.exc_info[0])
        self.eng.thread_group_mgr.start.assert_called_once_with(
            None, stack.purge_db)

    def test_get_environment(self):
        # Setup
        t = template_format.parse(tools.wp_template)
        env = {'parameters': {'KeyName': 'EnvKey'}}
        tmpl = templatem.Template(t)
        stack = parser.Stack(self.ctx, 'get_env_stack', tmpl)

        mock_get_stack = self.patchobject(self.eng, '_get_stack')
        mock_get_stack.return_value = mock.MagicMock()
        mock_get_stack.return_value.raw_template.environment = env
        self.patchobject(parser.Stack, 'load', return_value=stack)

        # Test
        found = self.eng.get_environment(self.ctx, stack.identifier())

        # Verify
        self.assertEqual(env, found)

    def test_get_environment_no_env(self):
        # Setup
        exc = exception.EntityNotFound(entity='stack', name='missing')
        self.patchobject(self.eng, '_get_stack', side_effect=exc)

        # Test
        self.assertRaises(dispatcher.ExpectedException,
                          self.eng.get_environment,
                          self.ctx,
                          'irrelevant')

    def test_get_files(self):
        # Setup
        t = template_format.parse(tools.wp_template)
        files = {'foo.yaml': 'i am a file'}
        tmpl = templatem.Template(t, files=files)
        stack = parser.Stack(self.ctx, 'get_env_stack', tmpl)
        stack.store()

        mock_get_stack = self.patchobject(self.eng, '_get_stack')
        mock_get_stack.return_value = mock.MagicMock()
        self.patchobject(templatem.Template, 'load', return_value=tmpl)

        # Test
        found = self.eng.get_files(self.ctx, stack.identifier())

        # Verify
        self.assertEqual(files, found)

    def test_stack_show_output(self):
        t = template_format.parse(tools.wp_template)
        t['outputs'] = {'test': {'value': 'first', 'description': 'sec'},
                        'test2': {'value': 'sec'}}
        tmpl = templatem.Template(t)
        stack = parser.Stack(self.ctx, 'service_list_outputs_stack', tmpl)

        self.patchobject(self.eng, '_get_stack')
        self.patchobject(parser.Stack, 'load', return_value=stack)

        output = self.eng.show_output(self.ctx, mock.ANY, 'test')
        self.assertEqual({'output_key': 'test', 'output_value': 'first',
                          'description': 'sec'},
                         output)

        # Ensure that stack raised NotFound error with incorrect key.
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.eng.show_output,
                               self.ctx, mock.ANY, 'bunny')
        self.assertEqual(exception.NotFound, ex.exc_info[0])
        self.assertEqual('Specified output key bunny not found.',
                         six.text_type(ex.exc_info[1]))

    def test_stack_show_output_error(self):
        t = template_format.parse(tools.wp_template)
        t['outputs'] = {'test': {'value': 'first', 'description': 'sec'}}
        tmpl = templatem.Template(t)
        stack = parser.Stack(self.ctx, 'service_list_outputs_stack', tmpl)

        self.patchobject(self.eng, '_get_stack')
        self.patchobject(parser.Stack, 'load', return_value=stack)
        self.patchobject(
            stack.outputs['test'], 'get_value',
            side_effect=[exception.EntityNotFound(entity='one', name='name')])

        output = self.eng.show_output(self.ctx, mock.ANY, 'test')
        self.assertEqual(
            {'output_key': 'test',
             'output_error': "The one (name) could not be found.",
             'description': 'sec',
             'output_value': None},
            output)

    def test_stack_list_all_empty(self):
        sl = self.eng.list_stacks(self.ctx)

        self.assertEqual(0, len(sl))

    def test_stack_describe_all_empty(self):
        sl = self.eng.show_stack(self.ctx, None, resolve_outputs=True)

        self.assertEqual(0, len(sl))

    def test_get_template(self):
        # Setup
        t = template_format.parse(tools.wp_template)
        tmpl = templatem.Template(t)
        stack = parser.Stack(self.ctx, 'get_env_stack', tmpl)

        mock_get_stack = self.patchobject(self.eng, '_get_stack')
        mock_get_stack.return_value = mock.MagicMock()
        mock_get_stack.return_value.raw_template.template = t
        self.patchobject(parser.Stack, 'load', return_value=stack)

        # Test
        found = self.eng.get_template(self.ctx, stack.identifier())

        # Verify
        self.assertEqual(t, found)

    def test_get_template_no_template(self):
        # Setup
        exc = exception.EntityNotFound(entity='stack', name='missing')
        self.patchobject(self.eng, '_get_stack', side_effect=exc)

        # Test
        self.assertRaises(dispatcher.ExpectedException,
                          self.eng.get_template,
                          self.ctx,
                          'missing')

    def _preview_stack(self, environment_files=None):
        res._register_class('GenericResource1', generic_rsrc.GenericResource)
        res._register_class('GenericResource2', generic_rsrc.GenericResource)

        args = {}
        params = {}
        files = None
        stack_name = 'SampleStack'
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Description': 'Lorem ipsum.',
               'Resources': {
                   'SampleResource1': {'Type': 'GenericResource1'},
                   'SampleResource2': {'Type': 'GenericResource2'}}}

        return self.eng.preview_stack(self.ctx, stack_name, tpl,
                                      params, files, args,
                                      environment_files=environment_files)

    def test_preview_stack_returns_a_stack(self):
        stack = self._preview_stack()
        expected_identity = {'path': '',
                             'stack_id': 'None',
                             'stack_name': 'SampleStack',
                             'tenant': 'stack_service_test_tenant'}
        self.assertEqual(expected_identity, stack['stack_identity'])
        self.assertEqual('SampleStack', stack['stack_name'])
        self.assertEqual('Lorem ipsum.', stack['description'])

    def test_preview_stack_returns_list_of_resources_in_stack(self):
        stack = self._preview_stack()
        self.assertIsInstance(stack['resources'], list)
        self.assertEqual(2, len(stack['resources']))

        resource_types = set(r['resource_type'] for r in stack['resources'])
        self.assertIn('GenericResource1', resource_types)
        self.assertIn('GenericResource2', resource_types)

        resource_names = set(r['resource_name'] for r in stack['resources'])
        self.assertIn('SampleResource1', resource_names)
        self.assertIn('SampleResource2', resource_names)

    def test_preview_stack_validates_new_stack(self):
        exc = exception.StackExists(stack_name='Validation Failed')
        self.eng._validate_new_stack = mock.Mock(side_effect=exc)
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._preview_stack)
        self.assertEqual(exception.StackExists, ex.exc_info[0])

    @mock.patch.object(service.api, 'format_stack_preview', new=mock.Mock())
    @mock.patch.object(service.parser, 'Stack')
    def test_preview_stack_checks_stack_validity(self, mock_parser):
        self.patchobject(policy.ResourceEnforcer, 'enforce_stack')
        exc = exception.StackValidationFailed(message='Validation Failed')
        mock_parsed_stack = mock.Mock()
        mock_parsed_stack.validate.side_effect = exc
        mock_parser.return_value = mock_parsed_stack
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self._preview_stack)
        self.assertEqual(exception.StackValidationFailed, ex.exc_info[0])

    @mock.patch.object(env_util, 'merge_environments')
    def test_preview_environment_files(self, mock_merge):
        # Setup
        environment_files = ['env_1']

        # Test
        self._preview_stack(environment_files=environment_files)

        # Verify
        mock_merge.assert_called_once_with(environment_files, None, {}, {})

    @mock.patch.object(stack_object.Stack, 'get_by_name')
    def test_validate_new_stack_checks_existing_stack(self, mock_stack_get):
        mock_stack_get.return_value = 'existing_db_stack'
        tmpl = templatem.Template(
            {'HeatTemplateFormatVersion': '2012-12-12'})
        self.assertRaises(exception.StackExists, self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', tmpl)

    @mock.patch.object(stack_object.Stack, 'count_all')
    def test_validate_new_stack_checks_stack_limit(self, mock_db_count):
        cfg.CONF.set_override('max_stacks_per_tenant', 99)
        mock_db_count.return_value = 99
        template = templatem.Template(
            {'HeatTemplateFormatVersion': '2012-12-12'})
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', template)

    def test_validate_new_stack_checks_incorrect_keywords_in_resource(self):
        template = {'heat_template_version': '2013-05-23',
                    'resources': {
                        'Res': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.eng._validate_new_stack,
                               self.ctx, 'test_existing_stack',
                               parsed_template)
        msg = (u'"Type" is not a valid keyword '
               'inside a resource definition')

        self.assertEqual(msg, six.text_type(ex))

    def test_validate_new_stack_checks_incorrect_sections(self):
        template = {'heat_template_version': '2013-05-23',
                    'unknown_section': {
                        'Res': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.eng._validate_new_stack,
                               self.ctx, 'test_existing_stack',
                               parsed_template)
        msg = u'The template section is invalid: unknown_section'
        self.assertEqual(msg, six.text_type(ex))

    def test_validate_new_stack_checks_resource_limit(self):
        cfg.CONF.set_override('max_resources_per_stack', 5)
        template = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {
                        'Res1': {'Type': 'GenericResource1'},
                        'Res2': {'Type': 'GenericResource1'},
                        'Res3': {'Type': 'GenericResource1'},
                        'Res4': {'Type': 'GenericResource1'},
                        'Res5': {'Type': 'GenericResource1'},
                        'Res6': {'Type': 'GenericResource1'}}}
        parsed_template = templatem.Template(template)
        self.assertRaises(exception.RequestLimitExceeded,
                          self.eng._validate_new_stack,
                          self.ctx, 'test_existing_stack', parsed_template)

    def test_validate_new_stack_handle_assertion_error(self):
        tmpl = mock.MagicMock()
        expected_message = 'Expected assertion error'
        tmpl.validate.side_effect = AssertionError(expected_message)
        exc = self.assertRaises(AssertionError, self.eng._validate_new_stack,
                                self.ctx, 'stack_name', tmpl)
        self.assertEqual(expected_message, six.text_type(exc))

    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch.object(stack_object.Stack, 'get_all')
    @mock.patch.object(stack_object.Stack, 'get_by_id')
    @mock.patch('heat.engine.stack_lock.StackLock',
                return_value=mock.Mock())
    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(context, 'get_admin_context')
    def test_engine_reset_stack_status(
            self,
            mock_admin_context,
            mock_stack_load,
            mock_stacklock,
            mock_get_by_id,
            mock_get_all,
            mock_thread):
        mock_admin_context.return_value = self.ctx

        db_stack = mock.MagicMock()
        db_stack.id = 'foo'
        db_stack.status = 'IN_PROGRESS'
        db_stack.status_reason = None

        unlocked_stack = mock.MagicMock()
        unlocked_stack.id = 'bar'
        unlocked_stack.status = 'IN_PROGRESS'
        unlocked_stack.status_reason = None

        unlocked_stack_failed = mock.MagicMock()
        unlocked_stack_failed.id = 'bar'
        unlocked_stack_failed.status = 'FAILED'
        unlocked_stack_failed.status_reason = 'because'

        mock_get_all.return_value = [db_stack, unlocked_stack]
        mock_get_by_id.side_effect = [db_stack, unlocked_stack_failed]

        fake_stack = mock.MagicMock()
        fake_stack.action = 'CREATE'
        fake_stack.id = 'foo'
        fake_stack.status = 'IN_PROGRESS'

        mock_stack_load.return_value = fake_stack

        lock1 = mock.MagicMock()
        lock1.get_engine_id.return_value = 'old-engine'
        lock1.acquire.return_value = None
        lock2 = mock.MagicMock()
        lock2.acquire.return_value = None
        mock_stacklock.side_effect = [lock1, lock2]

        self.eng.thread_group_mgr = mock_thread

        self.eng.reset_stack_status()

        mock_admin_context.assert_called()
        filters = {
            'status': parser.Stack.IN_PROGRESS,
            'convergence': False
        }
        mock_get_all.assert_called_once_with(self.ctx,
                                             filters=filters,
                                             show_nested=True)
        mock_get_by_id.assert_has_calls([
            mock.call(self.ctx, 'foo'),
            mock.call(self.ctx, 'bar'),
        ])
        mock_stack_load.assert_called_once_with(self.ctx,
                                                stack=db_stack)
        self.assertTrue(lock2.release.called)
        reason = ('Engine went down during stack %s' % fake_stack.action)
        mock_thread.start_with_acquired_lock.assert_called_once_with(
            fake_stack, lock1,
            fake_stack.reset_stack_and_resources_in_progress, reason
        )

    def test_parse_adopt_stack_data_without_parameters(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        template = {"heat_template_version": "2015-04-30",
                    "resources": {
                        "myres": {
                            "type": "OS::Cinder::Volume",
                            "properties": {
                                "name": "volname",
                                "size": "1"
                            }
                        }
                    }}

        # Assert no KeyError exception raised like before, when trying to
        # get parameters from adopt stack data which doesn't have it.
        args = {"adopt_stack_data": '''{}'''}
        self.eng._parse_template_and_validate_stack(
            self.ctx, 'stack_name', template, {}, {},
            None, None, args)

        args = {"adopt_stack_data": '''{
            "environment": {}
        }'''}
        self.eng._parse_template_and_validate_stack(
            self.ctx, 'stack_name', template, {}, {},
            None, None, args)

    def test_parse_adopt_stack_data_with_parameters(self):
        cfg.CONF.set_override('enable_stack_adopt', True)
        template = {"heat_template_version": "2015-04-30",
                    "parameters": {
                        "volsize": {"type": "number"}
                    },
                    "resources": {
                        "myres": {
                            "type": "OS::Cinder::Volume",
                            "properties": {
                                "name": "volname",
                                "size": {"get_param": "volsize"}
                            }
                        }
                    }}

        args = {"adopt_stack_data": '''{
            "environment": {
                "parameters": {
                    "volsize": 1
                }
            }}'''}
        stack = self.eng._parse_template_and_validate_stack(
            self.ctx, 'stack_name', template, {}, {},
            None, None, args)
        self.assertEqual(1, stack.parameters['volsize'])

    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch.object(stack_object.Stack, 'get_by_id')
    @mock.patch.object(parser.Stack, 'load')
    def test_stack_cancel_update_convergence_with_no_rollback(
            self, mock_load, mock_get_by_id, mock_tg):
        stk = mock.MagicMock()
        stk.id = 1
        stk.UPDATE = 'UPDATE'
        stk.IN_PROGRESS = 'IN_PROGRESS'
        stk.state = ('UPDATE', 'IN_PROGRESS')
        stk.status = stk.IN_PROGRESS
        stk.action = stk.UPDATE
        stk.convergence = True
        mock_load.return_value = stk
        self.patchobject(self.eng, '_get_stack')
        self.eng.thread_group_mgr.start = mock.MagicMock()
        with mock.patch.object(self.eng, 'worker_service') as mock_ws:
            mock_ws.stop_traversal = mock.Mock()
            # with rollback as false
            self.eng.stack_cancel_update(self.ctx, 1,
                                         cancel_with_rollback=False)
            self.assertTrue(self.eng.thread_group_mgr.start.called)
            call_args, _ = self.eng.thread_group_mgr.start.call_args
            # test ID of stack
            self.assertEqual(call_args[0], 1)
            # ensure stop_traversal should be called with stack
            self.assertEqual(call_args[1].func, mock_ws.stop_traversal)
            self.assertEqual(call_args[1].args[0], stk)

    @mock.patch('heat.engine.service.ThreadGroupManager',
                return_value=mock.Mock())
    @mock.patch.object(stack_object.Stack, 'get_by_id')
    @mock.patch.object(parser.Stack, 'load')
    def test_stack_cancel_update_convergence_with_rollback(
            self, mock_load, mock_get_by_id, mock_tg):
        stk = mock.MagicMock()
        stk.id = 1
        stk.UPDATE = 'UPDATE'
        stk.IN_PROGRESS = 'IN_PROGRESS'
        stk.state = ('UPDATE', 'IN_PROGRESS')
        stk.status = stk.IN_PROGRESS
        stk.action = stk.UPDATE
        stk.convergence = True
        stk.rollback = mock.MagicMock(return_value=None)
        mock_load.return_value = stk
        self.patchobject(self.eng, '_get_stack')
        self.eng.thread_group_mgr.start = mock.MagicMock()
        # with rollback as true
        self.eng.stack_cancel_update(self.ctx, 1,
                                     cancel_with_rollback=True)
        self.eng.thread_group_mgr.start.assert_called_once_with(
            1, stk.rollback)
