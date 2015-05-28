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

import collections
import copy
import json
import time

import mock
import mox
from oslo_config import cfg
import six

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.db import api as db_api
from heat.engine.clients.os import keystone
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack
from heat.engine import template
from heat.objects import stack as stack_object
from heat.objects import stack_tag as stack_tag_object
from heat.objects import user_creds as ucreds_object
from heat.tests import common
from heat.tests import fakes
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

empty_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
}''')


class StackTest(common.HeatTestCase):
    def setUp(self):
        super(StackTest, self).setUp()

        self.tmpl = template.Template(copy.deepcopy(empty_template))
        self.ctx = utils.dummy_context()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithPropsType',
                                 generic_rsrc.ResourceWithProps)
        resource._register_class('ResWithComplexPropsAndAttrs',
                                 generic_rsrc.ResWithComplexPropsAndAttrs)

    def test_stack_reads_tenant(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 tenant_id='bar')
        self.assertEqual('bar', self.stack.tenant_id)

    def test_stack_reads_tenant_from_context_if_empty(self):
        self.ctx.tenant_id = 'foo'
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 tenant_id=None)
        self.assertEqual('foo', self.stack.tenant_id)

    def test_stack_reads_username(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 username='bar')
        self.assertEqual('bar', self.stack.username)

    def test_stack_reads_username_from_context_if_empty(self):
        self.ctx.username = 'foo'
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 username=None)
        self.assertEqual('foo', self.stack.username)

    def test_stack_string_repr(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        expected = 'Stack "%s" [%s]' % (self.stack.name, self.stack.id)
        observed = str(self.stack)
        self.assertEqual(expected, observed)

    def test_state_defaults(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        self.assertEqual(('CREATE', 'IN_PROGRESS'), self.stack.state)
        self.assertEqual('', self.stack.status_reason)

    def test_timeout_secs_default(self):
        cfg.CONF.set_override('stack_action_timeout', 1000)
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        self.assertIsNone(self.stack.timeout_mins)
        self.assertEqual(1000, self.stack.timeout_secs())

    def test_timeout_secs(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 timeout_mins=10)
        self.assertEqual(600, self.stack.timeout_secs())

    def test_no_auth_token(self):
        ctx = utils.dummy_context()
        ctx.auth_token = None
        self.stub_auth()

        self.m.ReplayAll()
        self.stack = stack.Stack(ctx, 'test_stack', self.tmpl)
        self.assertEqual('abcd1234',
                         self.stack.clients.client('keystone').auth_token)

        self.m.VerifyAll()

    def test_state(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 action=stack.Stack.CREATE,
                                 status=stack.Stack.IN_PROGRESS)
        self.assertEqual((stack.Stack.CREATE, stack.Stack.IN_PROGRESS),
                         self.stack.state)
        self.stack.state_set(stack.Stack.CREATE, stack.Stack.COMPLETE, 'test')
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.stack.state_set(stack.Stack.DELETE, stack.Stack.COMPLETE, 'test')
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_state_deleted(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 action=stack.Stack.CREATE,
                                 status=stack.Stack.IN_PROGRESS)
        self.stack.id = '1234'

        # Simulate a deleted stack
        self.m.StubOutWithMock(stack_object.Stack, 'get_by_id')
        stack_object.Stack.get_by_id(self.stack.context,
                                     self.stack.id).AndReturn(None)

        self.m.ReplayAll()

        self.assertIsNone(self.stack.state_set(stack.Stack.CREATE,
                                               stack.Stack.COMPLETE,
                                               'test'))
        self.m.VerifyAll()

    def test_state_bad(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 action=stack.Stack.CREATE,
                                 status=stack.Stack.IN_PROGRESS)
        self.assertEqual((stack.Stack.CREATE, stack.Stack.IN_PROGRESS),
                         self.stack.state)
        self.assertRaises(ValueError, self.stack.state_set,
                          'baad', stack.Stack.COMPLETE, 'test')
        self.assertRaises(ValueError, self.stack.state_set,
                          stack.Stack.CREATE, 'oops', 'test')

    def test_status_reason(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 status_reason='quux')
        self.assertEqual('quux', self.stack.status_reason)
        self.stack.state_set(stack.Stack.CREATE, stack.Stack.IN_PROGRESS,
                             'wibble')
        self.assertEqual('wibble', self.stack.status_reason)

    def test_load_nonexistant_id(self):
        self.assertRaises(exception.NotFound, stack.Stack.load,
                          None, -1)

    def test_total_resources_empty(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 status_reason='flimflam')
        self.assertEqual(0, self.stack.total_resources())

    def test_total_resources_generic(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')
        self.assertEqual(1, self.stack.total_resources())

    def test_total_resources_nested_ok(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')

        self.stack['A'].nested = mock.Mock()
        self.stack['A'].nested.return_value.total_resources.return_value = 3
        self.assertEqual(4, self.stack.total_resources())

    def test_total_resources_nested_not_found(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')

        self.stack['A'].nested = mock.Mock(
            side_effect=exception.NotFound('gone'))
        self.assertEqual(1, self.stack.total_resources())

    def test_iter_resources(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'},
                'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')

        def get_more(nested_depth=0):
            yield 'X'
            yield 'Y'
            yield 'Z'

        self.stack['A'].nested = mock.MagicMock()
        self.stack['A'].nested.return_value.iter_resources = mock.MagicMock(
            side_effect=get_more)

        resource_generator = self.stack.iter_resources()
        self.assertIsNot(resource_generator, list)

        first_level_resources = list(resource_generator)
        self.assertEqual(2, len(first_level_resources))
        all_resources = list(self.stack.iter_resources(1))
        self.assertEqual(5, len(all_resources))

    @mock.patch.object(stack.Stack, 'db_resource_get')
    def test_iter_resources_cached(self, mock_drg):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'},
                'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg',
                                 cache_data={})

        def get_more(nested_depth=0):
            yield 'X'
            yield 'Y'
            yield 'Z'

        self.stack['A'].nested = mock.MagicMock()
        self.stack['A'].nested.return_value.iter_resources = mock.MagicMock(
            side_effect=get_more)

        resource_generator = self.stack.iter_resources()
        self.assertIsNot(resource_generator, list)

        first_level_resources = list(resource_generator)
        self.assertEqual(2, len(first_level_resources))
        all_resources = list(self.stack.iter_resources(1))
        self.assertEqual(5, len(all_resources))

        # A cache supplied means we should never query the database.
        self.assertFalse(mock_drg.called)

    def test_root_stack_no_parent(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')

        self.assertEqual(self.stack, self.stack.root_stack)

    def test_root_stack_parent_no_stack(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg',
                                 parent_resource='parent')

        parent_resource = mock.Mock()
        parent_resource.stack = None
        self.stack._parent_stack = dict(parent=parent_resource)
        self.assertEqual(self.stack, self.stack.root_stack)

    def test_root_stack_with_parent(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        stk = stack.Stack(self.ctx, 'test_stack', template.Template(tpl),
                          status_reason='blarg', parent_resource='parent')

        parent_resource = mock.Mock()
        parent_resource.stack.root_stack = 'test value'
        stk._parent_stack = dict(parent=parent_resource)
        self.assertEqual('test value', stk.root_stack)

    def test_load_parent_resource(self):
        self.stack = stack.Stack(self.ctx, 'load_parent_resource', self.tmpl,
                                 parent_resource='parent')
        self.stack.store()
        stk = stack_object.Stack.get_by_id(self.ctx, self.stack.id)

        t = template.Template.load(self.ctx, stk.raw_template_id)
        self.m.StubOutWithMock(template.Template, 'load')
        template.Template.load(
            self.ctx, stk.raw_template_id, stk.raw_template
        ).AndReturn(t)

        self.m.StubOutWithMock(stack.Stack, '__init__')
        stack.Stack.__init__(self.ctx, stk.name, t, stack_id=stk.id,
                             action=stk.action, status=stk.status,
                             status_reason=stk.status_reason,
                             timeout_mins=stk.timeout, resolve_data=True,
                             disable_rollback=stk.disable_rollback,
                             parent_resource='parent', owner_id=None,
                             stack_user_project_id=None,
                             created_time=mox.IgnoreArg(),
                             updated_time=None,
                             user_creds_id=stk.user_creds_id,
                             tenant_id='test_tenant_id',
                             use_stored_context=False,
                             username=mox.IgnoreArg(),
                             convergence=False,
                             current_traversal=None,
                             tags=mox.IgnoreArg(),
                             prev_raw_template_id=None,
                             current_deps=None, cache_data=None)

        self.m.ReplayAll()
        stack.Stack.load(self.ctx, stack_id=self.stack.id)

        self.m.VerifyAll()

    def test_identifier(self):
        self.stack = stack.Stack(self.ctx, 'identifier_test', self.tmpl)
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(self.stack.tenant_id, identifier.tenant)
        self.assertEqual('identifier_test', identifier.stack_name)
        self.assertTrue(identifier.stack_id)
        self.assertFalse(identifier.path)

    def test_get_stack_abandon_data(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Parameters': {'param1': {'Type': 'String'}},
               'Resources':
               {'A': {'Type': 'GenericResourceType'},
                'B': {'Type': 'GenericResourceType'}}}
        resources = '''{"A": {"status": "COMPLETE", "name": "A",
        "resource_data": {}, "resource_id": null, "action": "INIT",
        "type": "GenericResourceType", "metadata": {}},
        "B": {"status": "COMPLETE", "name": "B", "resource_data": {},
        "resource_id": null, "action": "INIT", "type": "GenericResourceType",
        "metadata": {}}}'''
        env = environment.Environment({'parameters': {'param1': 'test'}})
        self.stack = stack.Stack(self.ctx, 'stack_details_test',
                                 template.Template(tpl, env=env),
                                 tenant_id='123',
                                 stack_user_project_id='234')
        self.stack.store()
        info = self.stack.prepare_abandon()
        self.assertEqual('CREATE', info['action'])
        self.assertIn('id', info)
        self.assertEqual('stack_details_test', info['name'])
        self.assertEqual(json.loads(resources), info['resources'])
        self.assertEqual('IN_PROGRESS', info['status'])
        self.assertEqual(tpl, info['template'])
        self.assertEqual('123', info['project_id'])
        self.assertEqual('234', info['stack_user_project_id'])
        self.assertEqual(env.params, info['environment']['parameters'])

    def test_set_param_id(self):
        self.stack = stack.Stack(self.ctx, 'param_arn_test', self.tmpl)
        exp_prefix = ('arn:openstack:heat::test_tenant_id'
                      ':stacks/param_arn_test/')
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         exp_prefix + 'None')
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(exp_prefix + self.stack.id,
                         self.stack.parameters['AWS::StackId'])
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         identifier.arn())
        self.m.VerifyAll()

    def test_set_param_id_update(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Metadata': {'Bar': {'Ref': 'AWS::StackId'}},
                                  'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_stack_arn_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        stack_arn = self.stack.parameters['AWS::StackId']

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'ResourceWithPropsType',
                                   'Metadata': {'Bar':
                                                {'Ref': 'AWS::StackId'}},
                                   'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])

        self.assertEqual(
            stack_arn, self.stack['AResource'].metadata_get()['Bar'])

    def test_load_param_id(self):
        self.stack = stack.Stack(self.ctx, 'param_load_arn_test', self.tmpl)
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         identifier.arn())

        newstack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(identifier.arn(), newstack.parameters['AWS::StackId'])

    def test_load_reads_tenant_id(self):
        self.ctx.tenant_id = 'foobar'
        self.stack = stack.Stack(self.ctx, 'stack_name', self.tmpl)
        self.stack.store()
        stack_id = self.stack.id
        self.ctx.tenant_id = None
        self.stack = stack.Stack.load(self.ctx, stack_id=stack_id)
        self.assertEqual('foobar', self.stack.tenant_id)

    def test_load_reads_username_from_db(self):
        self.ctx.username = 'foobar'
        self.stack = stack.Stack(self.ctx, 'stack_name', self.tmpl)
        self.stack.store()
        stack_id = self.stack.id

        self.ctx.username = None
        stk = stack.Stack.load(self.ctx, stack_id=stack_id)
        self.assertEqual('foobar', stk.username)

        self.ctx.username = 'not foobar'
        stk = stack.Stack.load(self.ctx, stack_id=stack_id)
        self.assertEqual('foobar', stk.username)

    def test_load_all(self):
        stack1 = stack.Stack(self.ctx, 'stack1', self.tmpl)
        stack1.store()
        stack2 = stack.Stack(self.ctx, 'stack2', self.tmpl)
        stack2.store()

        stacks = list(stack.Stack.load_all(self.ctx))
        self.assertEqual(2, len(stacks))

        # Add another, nested, stack
        stack3 = stack.Stack(self.ctx, 'stack3', self.tmpl,
                             owner_id=stack2.id)
        stack3.store()

        # Should still be 2 without show_nested
        stacks = list(stack.Stack.load_all(self.ctx))
        self.assertEqual(2, len(stacks))

        stacks = list(stack.Stack.load_all(self.ctx, show_nested=True))
        self.assertEqual(3, len(stacks))

        # A backup stack should not be returned
        stack1._backup_stack()
        stacks = list(stack.Stack.load_all(self.ctx))
        self.assertEqual(2, len(stacks))

        stacks = list(stack.Stack.load_all(self.ctx, show_nested=True))
        self.assertEqual(3, len(stacks))

    def test_created_time(self):
        self.stack = stack.Stack(self.ctx, 'creation_time_test', self.tmpl)
        self.assertIsNone(self.stack.created_time)
        self.stack.store()
        self.assertIsNotNone(self.stack.created_time)

    def test_updated_time(self):
        self.stack = stack.Stack(self.ctx, 'updated_time_test',
                                 self.tmpl)
        self.assertIsNone(self.stack.updated_time)
        self.stack.store()
        self.stack.create()

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'R1': {'Type': 'GenericResourceType'}}}
        newstack = stack.Stack(self.ctx, 'updated_time_test',
                               template.Template(tmpl))
        self.stack.update(newstack)
        self.assertIsNotNone(self.stack.updated_time)

    def test_access_policy_update(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'R1': {'Type': 'GenericResourceType'},
                    'Policy': {
                        'Type': 'OS::Heat::AccessPolicy',
                        'Properties': {
                            'AllowedResources': ['R1']
                        }}}}

        self.stack = stack.Stack(self.ctx, 'update_stack_access_policy_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'R1': {'Type': 'GenericResourceType'},
                     'R2': {'Type': 'GenericResourceType'},
                     'Policy': {
                         'Type': 'OS::Heat::AccessPolicy',
                         'Properties': {
                             'AllowedResources': ['R1', 'R2'],
                         }}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_abandon_nodelete_project(self):
        self.stack = stack.Stack(self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        self.stack.set_stack_user_project_id(project_id='aproject456')

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(abandon=True)

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_suspend_resume(self):
        self.m.ReplayAll()
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'suspend_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)
        self.assertIsNone(self.stack.updated_time)

        self.stack.suspend()

        self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                         self.stack.state)
        stack_suspend_time = self.stack.updated_time
        self.assertIsNotNone(stack_suspend_time)

        self.stack.resume()

        self.assertEqual((self.stack.RESUME, self.stack.COMPLETE),
                         self.stack.state)
        self.assertNotEqual(stack_suspend_time, self.stack.updated_time)

        self.m.VerifyAll()

    def test_suspend_stack_suspended_ok(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'suspend_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.suspend()
        self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                         self.stack.state)

        # unexpected to call Resource.suspend
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'suspend')
        self.m.ReplayAll()

        self.stack.suspend()
        self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_resume_stack_resumeed_ok(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'suspend_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.suspend()
        self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.resume()
        self.assertEqual((self.stack.RESUME, self.stack.COMPLETE),
                         self.stack.state)

        # unexpected to call Resource.resume
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'resume')
        self.m.ReplayAll()

        self.stack.resume()
        self.assertEqual((self.stack.RESUME, self.stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_suspend_fail(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_suspend')
        exc = Exception('foo')
        generic_rsrc.GenericResource.handle_suspend().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'suspend_test_fail',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.suspend()

        self.assertEqual((self.stack.SUSPEND, self.stack.FAILED),
                         self.stack.state)
        self.assertEqual('Resource SUSPEND failed: Exception: foo',
                         self.stack.status_reason)
        self.m.VerifyAll()

    def test_resume_fail(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_resume')
        generic_rsrc.GenericResource.handle_resume().AndRaise(Exception('foo'))
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'resume_test_fail',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.suspend()

        self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.resume()

        self.assertEqual((self.stack.RESUME, self.stack.FAILED),
                         self.stack.state)
        self.assertEqual('Resource RESUME failed: Exception: foo',
                         self.stack.status_reason)
        self.m.VerifyAll()

    def test_suspend_timeout(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_suspend')
        exc = scheduler.Timeout('foo', 0)
        generic_rsrc.GenericResource.handle_suspend().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'suspend_test_fail_timeout',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.suspend()

        self.assertEqual((self.stack.SUSPEND, self.stack.FAILED),
                         self.stack.state)
        self.assertEqual('Suspend timed out', self.stack.status_reason)
        self.m.VerifyAll()

    def test_resume_timeout(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_resume')
        exc = scheduler.Timeout('foo', 0)
        generic_rsrc.GenericResource.handle_resume().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'resume_test_fail_timeout',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.suspend()

        self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.resume()

        self.assertEqual((self.stack.RESUME, self.stack.FAILED),
                         self.stack.state)

        self.assertEqual('Resume timed out', self.stack.status_reason)
        self.m.VerifyAll()

    def _get_stack_to_check(self, name):
        tpl = {"HeatTemplateFormatVersion": "2012-12-12",
               "Resources": {
                   "A": {"Type": "GenericResourceType"},
                   "B": {"Type": "GenericResourceType"}}}
        self.stack = stack.Stack(self.ctx, name, template.Template(tpl),
                                 status_reason=name)
        self.stack.store()

        def _mock_check(res):
            res.handle_check = mock.Mock()

        [_mock_check(res) for res in six.itervalues(self.stack.resources)]
        return self.stack

    def test_check_supported(self):
        stack1 = self._get_stack_to_check('check-supported')
        stack1.check()

        self.assertEqual(stack1.COMPLETE, stack1.status)
        self.assertEqual(stack1.CHECK, stack1.action)
        [self.assertTrue(res.handle_check.called)
         for res in six.itervalues(stack1.resources)]
        self.assertNotIn('not fully supported', stack1.status_reason)

    def test_check_not_supported(self):
        stack1 = self._get_stack_to_check('check-not-supported')
        del stack1['B'].handle_check
        stack1.check()

        self.assertEqual(stack1.COMPLETE, stack1.status)
        self.assertEqual(stack1.CHECK, stack1.action)
        self.assertTrue(stack1['A'].handle_check.called)
        self.assertIn('not fully supported', stack1.status_reason)

    def test_check_fail(self):
        stk = self._get_stack_to_check('check-fail')
        stk['A'].handle_check.side_effect = Exception('fail-A')
        stk['B'].handle_check.side_effect = Exception('fail-B')
        stk.check()

        self.assertEqual(stk.FAILED, stk.status)
        self.assertEqual(stk.CHECK, stk.action)
        self.assertTrue(stk['A'].handle_check.called)
        self.assertTrue(stk['B'].handle_check.called)
        self.assertIn('fail-A', stk.status_reason)
        self.assertIn('fail-B', stk.status_reason)

    def test_adopt_stack(self):
        adopt_data = '''{
        "action": "CREATE",
        "status": "COMPLETE",
        "name": "my-test-stack-name",
        "resources": {
        "AResource": {
        "status": "COMPLETE",
        "name": "AResource",
        "resource_data": {},
        "metadata": {},
        "resource_id": "test-res-id",
        "action": "CREATE",
        "type": "GenericResourceType"
          }
         }
        }'''

        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {'AResource': {'Type': 'GenericResourceType'}},
            'Outputs': {'TestOutput': {'Value': {
                'Fn::GetAtt': ['AResource', 'Foo']}}
            }
        }

        self.stack = stack.Stack(utils.dummy_context(), 'test_stack',
                                 template.Template(tmpl),
                                 adopt_stack_data=json.loads(adopt_data))
        self.stack.store()
        self.stack.adopt()
        res = self.stack['AResource']
        self.assertEqual(u'test-res-id', res.resource_id)
        self.assertEqual('AResource', res.name)
        self.assertEqual('COMPLETE', res.status)
        self.assertEqual('ADOPT', res.action)
        self.assertEqual((self.stack.ADOPT, self.stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('AResource', self.stack.output('TestOutput'))

        loaded_stack = stack.Stack.load(self.ctx, self.stack.id)
        self.assertEqual({}, loaded_stack['AResource']._stored_properties_data)

    def test_adopt_stack_fails(self):
        adopt_data = '''{
                "action": "CREATE",
                "status": "COMPLETE",
                "name": "my-test-stack-name",
                "resources": {}
                }'''

        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},

            }
        })
        self.stack = stack.Stack(utils.dummy_context(), 'test_stack',
                                 tmpl,
                                 adopt_stack_data=json.loads(adopt_data))
        self.stack.store()
        self.stack.adopt()
        self.assertEqual((self.stack.ADOPT, self.stack.FAILED),
                         self.stack.state)
        expected = ('Resource ADOPT failed: Exception: Resource ID was not'
                    ' provided.')
        self.assertEqual(expected, self.stack.status_reason)

    def test_adopt_stack_rollback(self):
        adopt_data = '''{
                "name": "my-test-stack-name",
                "resources": {}
                }'''

        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},

            }
        })
        self.stack = stack.Stack(utils.dummy_context(),
                                 'test_stack',
                                 tmpl,
                                 disable_rollback=False,
                                 adopt_stack_data=json.loads(adopt_data))
        self.stack.store()
        with mock.patch.object(self.stack, 'delete',
                               side_effect=self.stack.delete) as mock_delete:
            self.stack.adopt()
            self.assertEqual((self.stack.ROLLBACK, self.stack.COMPLETE),
                             self.stack.state)
            mock_delete.assert_called_once_with(action=self.stack.ROLLBACK,
                                                abandon=True)

    def test_resource_by_refid(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'resource_by_refid_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('AResource', self.stack)
        rsrc = self.stack['AResource']
        rsrc.resource_id_set('aaaa')
        self.assertIsNotNone(resource)

        for action, status in (
                (rsrc.INIT, rsrc.COMPLETE),
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)
            self.assertEqual(rsrc, self.stack.resource_by_refid('aaaa'))

        rsrc.state_set(rsrc.DELETE, rsrc.IN_PROGRESS)
        try:
            self.assertIsNone(self.stack.resource_by_refid('aaaa'))
            self.assertIsNone(self.stack.resource_by_refid('bbbb'))
        finally:
            rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE)

    def test_create_failure_recovery(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the second instance
        '''

        class ResourceTypeA(generic_rsrc.ResourceWithProps):
            count = 0

            def handle_create(self):
                ResourceTypeA.count += 1
                self.resource_id_set('%s%d' % (self.name, self.count))

            def handle_delete(self):
                return super(ResourceTypeA, self).handle_delete()

        resource._register_class('ResourceTypeA', ResourceTypeA)

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceTypeA',
                                  'Properties': {'Foo': 'abc'}},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {
                                      'Foo': {'Ref': 'AResource'}}}}}
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        self.m.StubOutWithMock(ResourceTypeA, 'handle_delete')

        # create
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)

        # update
        generic_rsrc.ResourceWithProps.handle_delete()
        generic_rsrc.ResourceWithProps.handle_create()

        self.m.ReplayAll()

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl),
                                    disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_create_bad_attribute(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'GenericResourceType'},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {
                                      'Foo': {'Fn::GetAtt': ['AResource',
                                                             'Foo']}}}}}
        self.stack = stack.Stack(self.ctx, 'bad_attr_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps,
                               '_update_stored_properties')

        generic_rsrc.ResourceWithProps._update_stored_properties().AndRaise(
            exception.InvalidTemplateAttribute(resource='a', key='foo'))

        self.m.ReplayAll()

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('Resource CREATE failed: The Referenced Attribute '
                         '(a foo) is incorrect.', self.stack.status_reason)
        self.m.VerifyAll()

    def test_stack_create_timeout(self):
        self.m.StubOutWithMock(scheduler.DependencyTaskGroup, '__call__')
        self.m.StubOutWithMock(scheduler, 'wallclock')

        stk = stack.Stack(self.ctx, 's', self.tmpl)

        def dummy_task():
            while True:
                yield

        start_time = time.time()
        scheduler.wallclock().AndReturn(start_time)
        scheduler.wallclock().AndReturn(start_time + 1)
        scheduler.DependencyTaskGroup.__call__().AndReturn(dummy_task())
        scheduler.wallclock().AndReturn(start_time + stk.timeout_secs() + 1)

        self.m.ReplayAll()

        stk.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.FAILED), stk.state)
        self.assertEqual('Create timed out', stk.status_reason)

        self.m.VerifyAll()

    def test_stack_name_valid(self):
        stk = stack.Stack(self.ctx, 's', self.tmpl)
        self.assertIsInstance(stk, stack.Stack)
        stk = stack.Stack(self.ctx, 'stack123', self.tmpl)
        self.assertIsInstance(stk, stack.Stack)
        stk = stack.Stack(self.ctx, 'test.stack', self.tmpl)
        self.assertIsInstance(stk, stack.Stack)
        stk = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        self.assertIsInstance(stk, stack.Stack)
        stk = stack.Stack(self.ctx, 'TEST', self.tmpl)
        self.assertIsInstance(stk, stack.Stack)
        stk = stack.Stack(self.ctx, 'test-stack', self.tmpl)
        self.assertIsInstance(stk, stack.Stack)

    def test_stack_name_invalid(self):
        stack_names = ['_foo', '1bad', '.kcats', 'test stack', ' teststack',
                       '^-^', '"stack"', '1234', 'cat|dog', '$(foo)',
                       'test/stack', 'test\stack', 'test::stack', 'test;stack',
                       'test~stack', '#test']
        for stack_name in stack_names:
            self.assertRaises(exception.StackValidationFailed, stack.Stack,
                              self.ctx, stack_name, self.tmpl)

    def test_resource_state_get_att(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {'AResource': {'Type': 'GenericResourceType'}},
            'Outputs': {'TestOutput': {'Value': {
                'Fn::GetAtt': ['AResource', 'Foo']}}
            }
        }

        self.stack = stack.Stack(self.ctx, 'resource_state_get_att',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('AResource', self.stack)
        rsrc = self.stack['AResource']
        rsrc.resource_id_set('aaaa')
        self.assertEqual('AResource', rsrc.FnGetAtt('Foo'))

        for action, status in (
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.CREATE, rsrc.FAILED),
                (rsrc.SUSPEND, rsrc.IN_PROGRESS),
                (rsrc.SUSPEND, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.FAILED),
                (rsrc.UPDATE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)
            self.assertEqual('AResource', self.stack.output('TestOutput'))
        for action, status in (
                (rsrc.DELETE, rsrc.IN_PROGRESS),
                (rsrc.DELETE, rsrc.FAILED),
                (rsrc.DELETE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)
            self.assertIsNone(self.stack.output('TestOutput'))

    def test_resource_required_by(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'},
                              'BResource': {'Type': 'GenericResourceType',
                                            'DependsOn': 'AResource'},
                              'CResource': {'Type': 'GenericResourceType',
                                            'DependsOn': 'BResource'},
                              'DResource': {'Type': 'GenericResourceType',
                                            'DependsOn': 'BResource'}}}

        self.stack = stack.Stack(self.ctx, 'depends_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(['BResource'],
                         self.stack['AResource'].required_by())
        self.assertEqual([],
                         self.stack['CResource'].required_by())
        required_by = self.stack['BResource'].required_by()
        self.assertEqual(2, len(required_by))
        for r in ['CResource', 'DResource']:
            self.assertIn(r, required_by)

    def test_resource_multi_required_by(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'},
                              'BResource': {'Type': 'GenericResourceType'},
                              'CResource': {'Type': 'GenericResourceType'},
                              'DResource': {'Type': 'GenericResourceType',
                                            'DependsOn': ['AResource',
                                                          'BResource',
                                                          'CResource']}}}

        self.stack = stack.Stack(self.ctx, 'depends_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        for r in ['AResource', 'BResource', 'CResource']:
            self.assertEqual(['DResource'],
                             self.stack[r].required_by())

    def test_store_saves_owner(self):
        """
        The owner_id attribute of Store is saved to the database when stored.
        """
        self.stack = stack.Stack(self.ctx, 'owner_stack', self.tmpl)
        stack_ownee = stack.Stack(self.ctx, 'ownee_stack', self.tmpl,
                                  owner_id=self.stack.id)
        stack_ownee.store()
        db_stack = stack_object.Stack.get_by_id(self.ctx, stack_ownee.id)
        self.assertEqual(self.stack.id, db_stack.owner_id)

    def test_init_user_creds_id(self):
        ctx_init = utils.dummy_context(user='my_user',
                                       password='my_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = ucreds_object.UserCreds.create(ctx_init)
        self.stack = stack.Stack(self.ctx, 'creds_init', self.tmpl,
                                 user_creds_id=creds.id)
        self.stack.store()
        self.assertEqual(creds.id, self.stack.user_creds_id)
        ctx_expected = ctx_init.to_dict()
        ctx_expected['auth_token'] = None
        self.assertEqual(ctx_expected, self.stack.stored_context().to_dict())

    def test_load_reads_tags(self):
        self.stack = stack.Stack(self.ctx, 'stack_tags', self.tmpl)
        self.stack.store()
        stack_id = self.stack.id
        test_stack = stack.Stack.load(self.ctx, stack_id=stack_id)
        self.assertIsNone(test_stack.tags)

        self.stack = stack.Stack(self.ctx, 'stack_name', self.tmpl,
                                 tags=['tag1', 'tag2'])
        self.stack.store()
        stack_id = self.stack.id
        test_stack = stack.Stack.load(self.ctx, stack_id=stack_id)
        self.assertEqual(['tag1', 'tag2'], test_stack.tags)

    def test_store_saves_tags(self):
        self.stack = stack.Stack(self.ctx, 'tags_stack', self.tmpl)
        self.stack.store()
        db_tags = stack_tag_object.StackTagList.get(self.stack.context,
                                                    self.stack.id)
        self.assertIsNone(db_tags)

        self.stack = stack.Stack(self.ctx, 'tags_stack', self.tmpl,
                                 tags=['tag1', 'tag2'])
        self.stack.store()
        db_tags = stack_tag_object.StackTagList.get(self.stack.context,
                                                    self.stack.id)
        self.assertEqual('tag1', db_tags[0].tag)
        self.assertEqual('tag2', db_tags[1].tag)

    def test_store_saves_creds(self):
        """
        A user_creds entry is created on first stack store
        """
        cfg.CONF.set_default('deferred_auth_method', 'password')
        self.stack = stack.Stack(self.ctx, 'creds_stack', self.tmpl)
        self.stack.store()

        # The store should've created a user_creds row and set user_creds_id
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        user_creds_id = db_stack.user_creds_id
        self.assertIsNotNone(user_creds_id)

        # should've stored the username/password in the context
        user_creds = ucreds_object.UserCreds.get_by_id(user_creds_id)
        self.assertEqual(self.ctx.username, user_creds.get('username'))
        self.assertEqual(self.ctx.password, user_creds.get('password'))
        self.assertIsNone(user_creds.get('trust_id'))
        self.assertIsNone(user_creds.get('trustor_user_id'))

        # Check the stored_context is as expected
        expected_context = context.RequestContext.from_dict(self.ctx.to_dict())
        expected_context.auth_token = None
        stored_context = self.stack.stored_context().to_dict()
        self.assertEqual(expected_context.to_dict(), stored_context)

        # Store again, ID should not change
        self.stack.store()
        self.assertEqual(user_creds_id, db_stack.user_creds_id)

    def test_store_saves_creds_trust(self):
        """
        A user_creds entry is created on first stack store
        """
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self.m.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
        keystone.KeystoneClientPlugin._create().AndReturn(
            fakes.FakeKeystoneClient(user_id='auser123'))
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'creds_stack', self.tmpl)
        self.stack.store()

        # The store should've created a user_creds row and set user_creds_id
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        user_creds_id = db_stack.user_creds_id
        self.assertIsNotNone(user_creds_id)

        # should've stored the trust_id and trustor_user_id returned from
        # FakeKeystoneClient.create_trust_context, username/password should
        # not have been stored
        user_creds = ucreds_object.UserCreds.get_by_id(user_creds_id)
        self.assertIsNone(user_creds.get('username'))
        self.assertIsNone(user_creds.get('password'))
        self.assertEqual('atrust', user_creds.get('trust_id'))
        self.assertEqual('auser123', user_creds.get('trustor_user_id'))

        # Check the stored_context is as expected
        expected_context = context.RequestContext(
            trust_id='atrust', trustor_user_id='auser123',
            request_id=self.ctx.request_id, is_admin=False).to_dict()
        stored_context = self.stack.stored_context().to_dict()
        self.assertEqual(expected_context, stored_context)

        # Store again, ID should not change
        self.stack.store()
        self.assertEqual(user_creds_id, db_stack.user_creds_id)

    def test_backup_copies_user_creds_id(self):
        ctx_init = utils.dummy_context(user='my_user',
                                       password='my_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = ucreds_object.UserCreds.create(ctx_init)
        self.stack = stack.Stack(self.ctx, 'creds_init', self.tmpl,
                                 user_creds_id=creds.id)
        self.stack.store()
        self.assertEqual(creds.id, self.stack.user_creds_id)
        backup = self.stack._backup_stack()
        self.assertEqual(creds.id, backup.user_creds_id)

    def test_stored_context_err(self):
        """
        Test stored_context error path.
        """
        self.stack = stack.Stack(self.ctx, 'creds_stack', self.tmpl)
        ex = self.assertRaises(exception.Error, self.stack.stored_context)
        expected_err = 'Attempt to use stored_context with no user_creds'
        self.assertEqual(expected_err, six.text_type(ex))

    def test_store_gets_username_from_stack(self):
        self.stack = stack.Stack(self.ctx, 'username_stack',
                                 self.tmpl, username='foobar')
        self.ctx.username = 'not foobar'
        self.stack.store()
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertEqual('foobar', db_stack.username)

    def test_store_backup_true(self):
        self.stack = stack.Stack(self.ctx, 'username_stack',
                                 self.tmpl, username='foobar')
        self.ctx.username = 'not foobar'
        self.stack.store(backup=True)
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertTrue(db_stack.backup)

    def test_store_backup_false(self):
        self.stack = stack.Stack(self.ctx, 'username_stack',
                                 self.tmpl, username='foobar')
        self.ctx.username = 'not foobar'
        self.stack.store(backup=False)
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertFalse(db_stack.backup)

    def test_init_stored_context_false(self):
        ctx_init = utils.dummy_context(user='mystored_user',
                                       password='mystored_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = ucreds_object.UserCreds.create(ctx_init)
        self.stack = stack.Stack(self.ctx, 'creds_store1', self.tmpl,
                                 user_creds_id=creds.id,
                                 use_stored_context=False)
        ctx_expected = self.ctx.to_dict()
        self.assertEqual(ctx_expected, self.stack.context.to_dict())
        self.stack.store()
        self.assertEqual(ctx_expected, self.stack.context.to_dict())

    def test_init_stored_context_true(self):
        ctx_init = utils.dummy_context(user='mystored_user',
                                       password='mystored_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = ucreds_object.UserCreds.create(ctx_init)
        self.stack = stack.Stack(self.ctx, 'creds_store2', self.tmpl,
                                 user_creds_id=creds.id,
                                 use_stored_context=True)
        ctx_expected = ctx_init.to_dict()
        ctx_expected['auth_token'] = None
        self.assertEqual(ctx_expected, self.stack.context.to_dict())
        self.stack.store()
        self.assertEqual(ctx_expected, self.stack.context.to_dict())

    def test_load_stored_context_false(self):
        ctx_init = utils.dummy_context(user='mystored_user',
                                       password='mystored_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = ucreds_object.UserCreds.create(ctx_init)
        self.stack = stack.Stack(self.ctx, 'creds_store3', self.tmpl,
                                 user_creds_id=creds.id)
        self.stack.store()

        load_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id,
                                      use_stored_context=False)
        self.assertEqual(self.ctx.to_dict(), load_stack.context.to_dict())

    def test_load_stored_context_true(self):
        ctx_init = utils.dummy_context(user='mystored_user',
                                       password='mystored_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = ucreds_object.UserCreds.create(ctx_init)
        self.stack = stack.Stack(self.ctx, 'creds_store4', self.tmpl,
                                 user_creds_id=creds.id)
        self.stack.store()
        ctx_expected = ctx_init.to_dict()
        ctx_expected['auth_token'] = None

        load_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id,
                                      use_stored_context=True)
        self.assertEqual(ctx_expected, load_stack.context.to_dict())

    def test_load_honors_owner(self):
        """
        Loading a stack from the database will set the owner_id of the
        resultant stack appropriately.
        """
        self.stack = stack.Stack(self.ctx, 'owner_stack', self.tmpl)
        stack_ownee = stack.Stack(self.ctx, 'ownee_stack', self.tmpl,
                                  owner_id=self.stack.id)
        stack_ownee.store()

        saved_stack = stack.Stack.load(self.ctx, stack_id=stack_ownee.id)
        self.assertEqual(self.stack.id, saved_stack.owner_id)

    def test_requires_deferred_auth(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'},
                              'BResource': {'Type': 'GenericResourceType'},
                              'CResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)

        self.assertFalse(self.stack.requires_deferred_auth())

        self.stack['CResource'].requires_deferred_auth = True
        self.assertTrue(self.stack.requires_deferred_auth())

    def test_stack_user_project_id_default(self):
        self.stack = stack.Stack(self.ctx, 'user_project_none', self.tmpl)
        self.stack.store()
        self.assertIsNone(self.stack.stack_user_project_id)
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertIsNone(db_stack.stack_user_project_id)

    def test_stack_user_project_id_constructor(self):
        self.stub_keystoneclient()
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'user_project_init',
                                 self.tmpl,
                                 stack_user_project_id='aproject1234')
        self.stack.store()
        self.assertEqual('aproject1234', self.stack.stack_user_project_id)
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertEqual('aproject1234', db_stack.stack_user_project_id)

        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_stack_user_project_id_setter(self):
        self.stub_keystoneclient()
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'user_project_init', self.tmpl)
        self.stack.store()
        self.assertIsNone(self.stack.stack_user_project_id)
        self.stack.set_stack_user_project_id(project_id='aproject456')
        self.assertEqual('aproject456', self.stack.stack_user_project_id)
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertEqual('aproject456', db_stack.stack_user_project_id)

        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_stack_user_project_id_create(self):
        self.stub_keystoneclient()
        self.m.ReplayAll()

        self.stack = stack.Stack(self.ctx, 'user_project_init', self.tmpl)
        self.stack.store()
        self.assertIsNone(self.stack.stack_user_project_id)
        self.stack.create_stack_user_project_id()

        self.assertEqual('aprojectid', self.stack.stack_user_project_id)
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertEqual('aprojectid', db_stack.stack_user_project_id)

        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_preview_resources_returns_list_of_resource_previews(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'preview_stack',
                                 template.Template(tmpl))
        res = mock.Mock()
        res.preview.return_value = 'foo'
        self.stack._resources = {'r1': res}

        resources = self.stack.preview_resources()
        self.assertEqual(['foo'], resources)

    def test_correct_outputs(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'abc'}},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'def'}}},
                'Outputs': {
                    'Resource_attr': {
                        'Value': {
                            'Fn::GetAtt': ['AResource', 'Foo']}}}}

        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        # According _resolve_attribute method in GenericResource output
        # value will be equal with name AResource.
        self.assertEqual('AResource', self.stack.output('Resource_attr'))

        self.stack.delete()

        self.assertEqual((self.stack.DELETE, self.stack.COMPLETE),
                         self.stack.state)

    def test_incorrect_outputs(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'abc'}}},
                'Outputs': {
                    'Resource_attr': {
                        'Value': {
                            'Fn::GetAtt': ['AResource', 'Bar']}}}}

        self.stack = stack.Stack(self.ctx, 'stack_with_incorrect_outputs',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.assertIsNone(self.stack.output('Resource_attr'))
        self.assertEqual('The Referenced Attribute (AResource Bar) is '
                         'incorrect.',
                         self.stack.outputs['Resource_attr']['error_msg'])

        self.stack.delete()

        self.assertEqual((self.stack.DELETE, self.stack.COMPLETE),
                         self.stack.state)

    def test_stack_load_no_param_value_validation(self):
        '''
        Test stack loading with disabled parameter value validation.
        '''
        tmpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            flavor:
                type: string
                description: A flavor.
                constraints:
                    - custom_constraint: nova.flavor
        resources:
            a_resource:
                type: GenericResourceType
        ''')

        # Mock objects so the query for flavors in server.FlavorConstraint
        # works for stack creation
        fc = fakes.FakeClient()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(fc)

        fc.flavors = self.m.CreateMockAnything()
        flavor = collections.namedtuple("Flavor", ["id", "name"])
        flavor.id = "1234"
        flavor.name = "dummy"
        fc.flavors.list().AndReturn([flavor])

        self.m.ReplayAll()

        test_env = environment.Environment({'flavor': 'dummy'})
        self.stack = stack.Stack(self.ctx, 'stack_with_custom_constraint',
                                 template.Template(tmpl, env=test_env))

        self.stack.validate()
        self.stack.store()
        self.stack.create()
        stack_id = self.stack.id

        self.m.VerifyAll()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        loaded_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(stack_id, loaded_stack.parameters['OS::stack_id'])

        # verify that fc.flavors.list() has not been called, i.e. verify that
        # parameter value validation did not happen and FlavorConstraint was
        # not invoked
        self.m.VerifyAll()

    def test_snapshot_delete(self):
        snapshots = []

        class ResourceDeleteSnapshot(generic_rsrc.ResourceWithProps):

            def handle_delete_snapshot(self, data):
                snapshots.append(data)

        resource._register_class(
            'ResourceDeleteSnapshot', ResourceDeleteSnapshot)
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceDeleteSnapshot'}}}

        self.stack = stack.Stack(self.ctx, 'snapshot_stack',
                                 template.Template(tmpl))
        data = self.stack.prepare_abandon()
        fake_snapshot = collections.namedtuple('Snapshot', ('data',))(data)
        self.stack.delete_snapshot(fake_snapshot)
        self.assertEqual([data['resources']['AResource']], snapshots)

    def test_delete_snapshot_without_data(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'R1': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'snapshot_stack',
                                 template.Template(tmpl))
        fake_snapshot = collections.namedtuple('Snapshot', ('data',))(None)
        self.assertIsNone(self.stack.delete_snapshot(fake_snapshot))

    def test_incorrect_outputs_cfn_get_attr(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'abc'}}},
                'Outputs': {
                    'Resource_attr': {
                        'Value': {
                            'Fn::GetAtt': ['AResource', 'Bar']}}}}

        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertEqual('Output validation error : '
                         'Outputs.Resource_attr.Value: '
                         'The Referenced Attribute '
                         '(AResource Bar) is incorrect.',
                         six.text_type(ex))

    def test_incorrect_outputs_cfn_incorrect_reference(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Outputs:
          Output:
            Value:
              Fn::GetAtt:
                - Resource
                - Foo
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_incorrect_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('The specified reference "Resource" '
                      '(in unknown) is incorrect.', six.text_type(ex))

    def test_incorrect_outputs_incorrect_reference(self):
        tmpl = template_format.parse("""
        heat_template_version: 2013-05-23
        outputs:
          output:
            value: { get_attr: [resource, foo] }
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_incorrect_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('The specified reference "resource" '
                      '(in unknown) is incorrect.', six.text_type(ex))

    def test_incorrect_outputs_cfn_empty_output(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Resources:
          AResource:
            Type: ResourceWithPropsType
            Properties:
              Foo: abc
        Outputs:
          Resource_attr:
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('Each Output must contain a Value key.',
                      six.text_type(ex))

    def test_incorrect_outputs_cfn_string_data(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Resources:
          AResource:
            Type: ResourceWithPropsType
            Properties:
              Foo: abc
        Outputs:
          Resource_attr:
            This is wrong data
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('Outputs must contain Output. '
                      'Found a [%s] instead' % six.text_type,
                      six.text_type(ex))

    def test_prop_validate_value(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Resources:
          AResource:
            Type: ResourceWithPropsType
            Properties:
              FooInt: notanint
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_bad_property',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn("'notanint' is not an integer",
                      six.text_type(ex))

        self.stack.strict_validate = False
        self.assertIsNone(self.stack.validate())

    def test_validate_property_getatt(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'R1': {'Type': 'ResourceWithPropsType'},
                'R2': {'Type': 'ResourceWithPropsType',
                       'Properties': {'Foo': {'Fn::GetAtt': ['R1', 'Foo']}}}}
        }
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tmpl))
        self.assertIsNone(self.stack.validate())

    def test_param_validate_value(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Parameters:
          foo:
            Type: Number
        """)

        env1 = environment.Environment({'parameters': {'foo': 'abc'}})
        self.stack = stack.Stack(self.ctx, 'stack_with_bad_param',
                                 template.Template(tmpl, env=env1))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertEqual("Parameter 'foo' is invalid: could not convert "
                         "string to float: abc", six.text_type(ex))

        self.stack.strict_validate = False
        self.assertIsNone(self.stack.validate())

    def test_incorrect_outputs_cfn_list_data(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Resources:
          AResource:
            Type: ResourceWithPropsType
            Properties:
              Foo: abc
        Outputs:
          Resource_attr:
            - Data is not what it seems
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('Outputs must contain Output. '
                      'Found a [%s] instead' % type([]), six.text_type(ex))

    def test_incorrect_outputs_hot_get_attr(self):
        tmpl = {'heat_template_version': '2013-05-23',
                'resources': {
                    'AResource': {'type': 'ResourceWithPropsType',
                                  'properties': {'Foo': 'abc'}}},
                'outputs': {
                    'resource_attr': {
                        'value': {
                            'get_attr': ['AResource', 'Bar']}}}}

        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertEqual('Output validation error : '
                         'outputs.resource_attr.value: '
                         'The Referenced Attribute '
                         '(AResource Bar) is incorrect.',
                         six.text_type(ex))

    def test_restore(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'A': {'Type': 'GenericResourceType'},
                    'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'stack_details_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()

        data = copy.deepcopy(self.stack.prepare_abandon())
        fake_snapshot = collections.namedtuple(
            'Snapshot', ('data', 'stack_id'))(data, self.stack.id)

        new_tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {'A': {'Type': 'GenericResourceType'}}}
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(new_tmpl))
        self.stack.update(updated_stack)
        self.assertEqual(1, len(self.stack.resources))

        self.stack.restore(fake_snapshot)

        self.assertEqual((stack.Stack.RESTORE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(2, len(self.stack.resources))

    def test_restore_with_original_env(self):
        tmpl = {
            'heat_template_version': '2013-05-23',
            'parameters': {
                'foo': {'type': 'string'}
            },
            'resources': {
                'A': {
                    'type': 'ResourceWithPropsType',
                    'properties': {'Foo': {'get_param': 'foo'}}
                }
            }
        }
        self.stack = stack.Stack(self.ctx, 'stack_restore_test',
                                 template.Template(
                                     tmpl,
                                     env=environment.Environment(
                                         {'foo': 'abc'})))
        self.stack.store()
        self.stack.create()
        self.assertEqual('abc',
                         self.stack.resources['A'].properties['Foo'])

        data = copy.deepcopy(self.stack.prepare_abandon())
        fake_snapshot = collections.namedtuple(
            'Snapshot', ('data', 'stack_id'))(data, self.stack.id)

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(
                                        tmpl,
                                        env=environment.Environment(
                                            {'foo': 'xyz'})))
        self.stack.update(updated_stack)
        self.assertEqual('xyz',
                         self.stack.resources['A'].properties['Foo'])

        self.stack.restore(fake_snapshot)
        self.assertEqual((stack.Stack.RESTORE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc',
                         self.stack.resources['A'].properties['Foo'])

    def test_hot_restore(self):

        class ResourceWithRestore(generic_rsrc.ResWithComplexPropsAndAttrs):

            def handle_restore(self, defn, data):
                props = dict(
                    (key, value) for (key, value) in
                    six.iteritems(defn.properties(self.properties_schema))
                    if value is not None)
                value = data['resource_data']['a_string']
                props['a_string'] = value
                return defn.freeze(properties=props)

        resource._register_class('ResourceWithRestore', ResourceWithRestore)
        tpl = {'heat_template_version': '2013-05-23',
               'resources':
               {'A': {'type': 'ResourceWithRestore'}}}
        self.stack = stack.Stack(self.ctx, 'stack_details_test',
                                 template.Template(tpl))
        self.stack.store()
        self.stack.create()

        data = self.stack.prepare_abandon()
        data['resources']['A']['resource_data']['a_string'] = 'foo'
        fake_snapshot = collections.namedtuple(
            'Snapshot', ('data', 'stack_id'))(data, self.stack.id)

        self.stack.restore(fake_snapshot)

        self.assertEqual((stack.Stack.RESTORE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(
            'foo', self.stack.resources['A'].properties['a_string'])

    @mock.patch.object(stack.Stack, 'db_resource_get')
    def test_lightweight_stack_getatt(self, mock_drg):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::GetAtt': ['foo', 'bar']},
                    }
                }
            }
        })

        cache_data = {'foo': {'attributes': {'bar': 'baz'}}}
        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl)
        tmpl_stack.store()
        lightweight_stack = stack.Stack.load(self.ctx, stack_id=tmpl_stack.id,
                                             cache_data=cache_data)

        # Check if the property has the appropriate resolved value.
        cached_property = lightweight_stack['bar'].properties['Foo']
        self.assertEqual(cached_property, 'baz')

        # Make sure FnGetAtt returns the cached value.
        attr_value = lightweight_stack['foo'].FnGetAtt('bar')
        self.assertEqual('baz', attr_value)

        # Make sure calls are not made to the database to retrieve the
        # resource state.
        self.assertFalse(mock_drg.called)

    @mock.patch.object(stack.Stack, 'db_resource_get')
    def test_lightweight_stack_getrefid(self, mock_drg):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'foo'},
                    }
                }
            }
        })

        cache_data = {'foo': {'id': 'physical-resource-id'}}
        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl)
        tmpl_stack.store()
        lightweight_stack = stack.Stack.load(self.ctx, stack_id=tmpl_stack.id,
                                             cache_data=cache_data)

        # Check if the property has the appropriate resolved value.
        cached_property = lightweight_stack['bar'].properties['Foo']
        self.assertEqual(cached_property, 'physical-resource-id')

        # Make sure FnGetRefId returns the cached value.
        resource_id = lightweight_stack['foo'].FnGetRefId()
        self.assertEqual('physical-resource-id', resource_id)

        # Make sure calls are not made to the database to retrieve the
        # resource state.
        self.assertFalse(mock_drg.called)

    def test_encrypt_parameters_false_parameters_stored_plaintext(self):
        '''
        Test stack loading with disabled parameter value validation.
        '''
        tmpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                description: value1.
            param2:
                type: string
                description: value2.
                hidden: true
        resources:
            a_resource:
                type: GenericResourceType
        ''')
        env1 = environment.Environment({'param1': 'foo', 'param2': 'bar'})
        self.stack = stack.Stack(self.ctx, 'test',
                                 template.Template(tmpl, env=env1))
        cfg.CONF.set_override('encrypt_parameters_and_properties', False)

        # Verify that hidden parameters stored in plain text
        self.stack.store()
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        params = db_stack.raw_template.environment['parameters']
        self.assertEqual('foo', params['param1'])
        self.assertEqual('bar', params['param2'])

    def test_parameters_stored_encrypted_decrypted_on_load(self):
        '''
        Test stack loading with disabled parameter value validation.
        '''
        tmpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                description: value1.
            param2:
                type: string
                description: value2.
                hidden: true
        resources:
            a_resource:
                type: GenericResourceType
        ''')
        env1 = environment.Environment({'param1': 'foo', 'param2': 'bar'})
        self.stack = stack.Stack(self.ctx, 'test',
                                 template.Template(tmpl, env=env1))
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)

        # Verify that hidden parameters are stored encrypted
        self.stack.store()
        db_tpl = db_api.raw_template_get(self.ctx, self.stack.t.id)
        db_params = db_tpl.environment['parameters']
        self.assertEqual('foo', db_params['param1'])
        self.assertEqual('oslo_decrypt_v1', db_params['param2'][0])
        self.assertIsNotNone(db_params['param2'][1])

        # Verify that loaded stack has decrypted paramters
        loaded_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        params = loaded_stack.t.env.params
        self.assertEqual('foo', params.get('param1'))
        self.assertEqual('bar', params.get('param2'))

    def test_parameters_stored_decrypted_successful_load(self):
        '''
        Test stack loading with disabled parameter value validation.
        '''
        tmpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
            param1:
                type: string
                description: value1.
            param2:
                type: string
                description: value2.
                hidden: true
        resources:
            a_resource:
                type: GenericResourceType
        ''')
        env1 = environment.Environment({'param1': 'foo', 'param2': 'bar'})
        self.stack = stack.Stack(self.ctx, 'test',
                                 template.Template(tmpl, env=env1))
        cfg.CONF.set_override('encrypt_parameters_and_properties', False)

        # Verify that hidden parameters are stored decrypted
        self.stack.store()
        db_tpl = db_api.raw_template_get(self.ctx, self.stack.t.id)
        db_params = db_tpl.environment['parameters']
        self.assertEqual('foo', db_params['param1'])
        self.assertEqual('bar', db_params['param2'])

        # Verify that stack loads without error
        loaded_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        params = loaded_stack.t.env.params
        self.assertEqual('foo', params.get('param1'))
        self.assertEqual('bar', params.get('param2'))


class StackKwargsForCloningTest(common.HeatTestCase):
    scenarios = [
        ('default', dict(keep_status=False, only_db=False,
                         not_included=['action', 'status', 'status_reason'])),
        ('only_db', dict(keep_status=False, only_db=True,
                         not_included=['action', 'status', 'status_reason',
                                       'strict_validate'])),
        ('keep_status', dict(keep_status=True, only_db=False,
                             not_included=[])),
        ('status_db', dict(keep_status=True, only_db=True,
                           not_included=['strict_validate'])),
    ]

    def test_kwargs(self):
        tmpl = template.Template(copy.deepcopy(empty_template))
        ctx = utils.dummy_context()
        test_data = dict(action='x', status='y',
                         status_reason='z', timeout_mins=33,
                         disable_rollback=True, parent_resource='fred',
                         owner_id=32, stack_user_project_id=569,
                         user_creds_id=123, tenant_id='some-uuid',
                         username='jo', nested_depth=3,
                         strict_validate=True, convergence=False,
                         current_traversal=45)
        db_map = {'parent_resource': 'parent_resource_name',
                  'tenant_id': 'tenant', 'timeout_mins': 'timeout'}
        test_db_data = {}
        for key in test_data:
            dbkey = db_map.get(key, key)
            test_db_data[dbkey] = test_data[key]

        self.stack = stack.Stack(ctx, utils.random_name(), tmpl,
                                 **test_data)
        res = self.stack.get_kwargs_for_cloning(keep_status=self.keep_status,
                                                only_db=self.only_db)
        for key in self.not_included:
            self.assertNotIn(key, res)

        for key in test_data:
            if key not in self.not_included:
                dbkey = db_map.get(key, key)
                if self.only_db:
                    self.assertEqual(test_data[key], res[dbkey])
                else:
                    self.assertEqual(test_data[key], res[key])

        if not self.only_db:
            # just make sure that the kwargs are valid
            # (no exception should be raised)
            stack.Stack(ctx, utils.random_name(), tmpl, **res)
