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
import datetime
import json
import logging
import time

import eventlet
import fixtures
import mock
from oslo_config import cfg
import six

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.common import timeutils
from heat.db.sqlalchemy import api as db_api
from heat.engine.clients.os import keystone
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine import function
from heat.engine import node_data
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import service
from heat.engine import stack
from heat.engine import stk_defn
from heat.engine import template
from heat.engine import update
from heat.objects import raw_template as raw_template_object
from heat.objects import resource as resource_objects
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
        self.stub_auth()

    def test_stack_reads_tenant(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 tenant_id='bar')
        self.assertEqual('bar', self.stack.tenant_id)

    def test_stack_reads_tenant_from_context_if_empty(self):
        self.ctx.tenant = 'foo'
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

    @mock.patch.object(stack, 'oslo_timeutils')
    def test_time_elapsed(self, mock_tu):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        # dummy create time 10:00:00
        self.stack.created_time = datetime.datetime(2015, 7, 27, 10, 0, 0)
        # mock utcnow set to 10:10:00 (600s offset)
        mock_tu.utcnow.return_value = datetime.datetime(2015, 7, 27, 10, 10, 0)
        self.assertEqual(600, self.stack.time_elapsed())

    @mock.patch.object(stack, 'oslo_timeutils')
    def test_time_elapsed_negative(self, mock_tu):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        # dummy create time 10:00:00
        self.stack.created_time = datetime.datetime(2015, 7, 27, 10, 0, 0)
        # mock utcnow set to 09:59:50 (-10s offset)
        mock_tu.utcnow.return_value = datetime.datetime(2015, 7, 27, 9, 59, 50)
        self.assertEqual(-10, self.stack.time_elapsed())

    @mock.patch.object(stack, 'oslo_timeutils')
    def test_time_elapsed_ms(self, mock_tu):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        # dummy create time 10:00:00
        self.stack.created_time = datetime.datetime(2015, 7, 27, 10, 5, 0)
        # mock utcnow set to microsecond offset
        mock_tu.utcnow.return_value = datetime.datetime(2015, 7, 27,
                                                        10, 4, 59, 750000)
        self.assertEqual(-0.25, self.stack.time_elapsed())

    @mock.patch.object(stack, 'oslo_timeutils')
    def test_time_elapsed_with_updated_time(self, mock_tu):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        # dummy create time 10:00:00
        self.stack.created_time = datetime.datetime(2015, 7, 27, 10, 0, 0)
        # dummy updated time 11:00:00; should consider this not created_time
        self.stack.updated_time = datetime.datetime(2015, 7, 27, 11, 0, 0)
        # mock utcnow set to 11:10:00 (600s offset)
        mock_tu.utcnow.return_value = datetime.datetime(2015, 7, 27, 11, 10, 0)
        self.assertEqual(600, self.stack.time_elapsed())

    @mock.patch.object(stack.Stack, 'time_elapsed')
    def test_time_remaining(self, mock_te):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        # mock time elapsed; set to 600 seconds
        mock_te.return_value = 600
        # default stack timeout is 3600 seconds; remaining time 3000 secs
        self.assertEqual(3000, self.stack.time_remaining())

    @mock.patch.object(stack.Stack, 'time_elapsed')
    def test_has_timed_out(self, mock_te):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl)
        self.stack.status = self.stack.IN_PROGRESS

        # test with timed out stack
        mock_te.return_value = 3601
        # default stack timeout is 3600 seconds; stack should time out
        self.assertTrue(self.stack.has_timed_out())

        # mock time elapsed; set to 600 seconds
        mock_te.return_value = 600
        # default stack timeout is 3600 seconds; remaining time 3000 secs
        self.assertFalse(self.stack.has_timed_out())

        # has_timed_out has no meaning when stack completes/fails;
        # should return false
        self.stack.status = self.stack.COMPLETE
        self.assertFalse(self.stack.has_timed_out())

        self.stack.status = self.stack.FAILED
        self.assertFalse(self.stack.has_timed_out())

    def test_no_auth_token(self):
        ctx = utils.dummy_context()
        ctx.auth_token = None

        self.stack = stack.Stack(ctx, 'test_stack', self.tmpl)
        self.assertEqual('abcd1234',
                         ctx.auth_plugin.auth_token)

    def test_state_deleted(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 action=stack.Stack.CREATE,
                                 status=stack.Stack.IN_PROGRESS)
        self.stack.id = '1234'

        self.stack.delete()
        self.assertIsNone(self.stack.state_set(stack.Stack.CREATE,
                                               stack.Stack.COMPLETE,
                                               'test'))

    def test_load_nonexistant_id(self):
        self.assertRaises(exception.NotFound, stack.Stack.load,
                          self.ctx, -1)

    def test_total_resources_empty(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 status_reason='flimflam')
        self.stack.store()
        self.assertEqual(0, self.stack.total_resources(self.stack.id))
        self.assertEqual(0, self.stack.total_resources())

    @mock.patch.object(db_api, 'stack_count_total_resources')
    def test_total_resources_not_stored(self, sctr):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 status_reason='flimflam')
        self.assertEqual(0, self.stack.total_resources())
        sctr.assert_not_called()

    def test_total_resources_not_found(self):
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 status_reason='flimflam')

        self.assertEqual(0, self.stack.total_resources('1234'))

    @mock.patch.object(db_api, 'stack_count_total_resources')
    def test_total_resources_generic(self, sctr):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')
        self.stack.store()
        sctr.return_value = 1
        self.assertEqual(1, self.stack.total_resources(self.stack.id))
        self.assertEqual(1, self.stack.total_resources())

    def test_resource_get(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')
        self.stack.store()
        self.assertEqual('A', self.stack.resource_get('A').name)
        self.assertEqual(self.stack['A'], self.stack.resource_get('A'))
        self.assertIsNone(self.stack.resource_get('B'))

    @mock.patch.object(resource_objects.Resource, 'get_all_by_stack')
    def test_resource_get_db_fallback(self, gabs):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')
        self.stack.store()
        tpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources':
                {'A': {'Type': 'GenericResourceType'},
                 'B': {'Type': 'GenericResourceType'}}}
        t2 = template.Template(tpl2)
        t2.store(self.ctx)

        db_resources = {
            'A': mock.MagicMock(),
            'B': mock.MagicMock(current_template_id=t2.id),
            'C': mock.MagicMock(current_template_id=t2.id)
        }
        db_resources['A'].name = 'A'
        db_resources['B'].name = 'B'
        db_resources['C'].name = 'C'
        gabs.return_value = db_resources

        self.assertEqual('A', self.stack.resource_get('A').name)
        self.assertEqual('B', self.stack.resource_get('B').name)

        # Ignore the resource if only in db
        self.assertIsNone(self.stack.resource_get('C'))
        self.assertIsNone(self.stack.resource_get('D'))

    @mock.patch.object(resource_objects.Resource, 'get_all_by_stack')
    def test_iter_resources(self, mock_db_call):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'},
                'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')
        self.stack.store()

        mock_rsc_a = mock.MagicMock(current_template_id=self.stack.t.id)
        mock_rsc_a.name = 'A'
        mock_rsc_b = mock.MagicMock(current_template_id=self.stack.t.id)
        mock_rsc_b.name = 'B'
        mock_db_call.return_value = {
            'A': mock_rsc_a,
            'B': mock_rsc_b
        }

        all_resources = list(self.stack.iter_resources())

        # Verify, the db query is called with expected filter
        mock_db_call.assert_called_once_with(self.ctx, self.stack.id)

        # And returns the resources
        names = sorted([r.name for r in all_resources])
        self.assertEqual(['A', 'B'], names)

    @mock.patch.object(resource_objects.Resource, 'get_all_by_stack')
    def test_iter_resources_with_nested(self, mock_db_call):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'StackResourceType'},
                'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')

        self.stack.store()

        mock_rsc_a = mock.MagicMock(current_template_id=self.stack.t.id)
        mock_rsc_a.name = 'A'
        mock_rsc_b = mock.MagicMock(current_template_id=self.stack.t.id)
        mock_rsc_b.name = 'B'
        mock_db_call.return_value = {
            'A': mock_rsc_a,
            'B': mock_rsc_b
        }

        def get_more(nested_depth=0, filters=None):
            yield 'X'
            yield 'Y'
            yield 'Z'

        mock_nested = self.patchobject(generic_rsrc.StackResourceType,
                                       'nested')
        mock_nested.return_value.iter_resources = mock.MagicMock(
            side_effect=get_more)

        resource_generator = self.stack.iter_resources()
        self.assertIsNot(resource_generator, list)

        first_level_resources = list(resource_generator)
        self.assertEqual(2, len(first_level_resources))
        all_resources = list(self.stack.iter_resources(1))
        self.assertEqual(5, len(all_resources))

    @mock.patch.object(resource_objects.Resource, 'get_all_by_stack')
    def test_iter_resources_with_filters(self, mock_db_call):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'},
                'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')
        self.stack.store()

        mock_rsc = mock.MagicMock()
        mock_rsc.name = 'A'
        mock_rsc.current_template_id = self.stack.t.id
        mock_db_call.return_value = {'A': mock_rsc}

        all_resources = list(self.stack.iter_resources(
            filters=dict(name=['A'])
        ))

        # Verify, the db query is called with expected filter
        mock_db_call.assert_has_calls([
            mock.call(self.ctx, self.stack.id, dict(name=['A'])),
            mock.call(self.ctx, self.stack.id),
        ])

        # Make sure it returns only one resource.
        self.assertEqual(1, len(all_resources))

        # And returns the resource A
        self.assertEqual('A', all_resources[0].name)

    @mock.patch.object(resource_objects.Resource, 'get_all_by_stack')
    def test_iter_resources_with_nonexistent_template(self, mock_db_call):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
                   {'A': {'Type': 'GenericResourceType'},
                    'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')

        self.stack.store()

        mock_rsc_a = mock.MagicMock(current_template_id=self.stack.t.id)
        mock_rsc_a.name = 'A'
        mock_rsc_b = mock.MagicMock(current_template_id=self.stack.t.id + 1)
        mock_rsc_b.name = 'B'
        mock_db_call.return_value = {
            'A': mock_rsc_a,
            'B': mock_rsc_b
        }

        all_resources = list(self.stack.iter_resources())

        self.assertEqual(1, len(all_resources))

    @mock.patch.object(resource_objects.Resource, 'get_all_by_stack')
    def test_iter_resources_nested_with_filters(self, mock_db_call):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
                   {'A': {'Type': 'StackResourceType'},
                    'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'test_stack',
                                 template.Template(tpl),
                                 status_reason='blarg')

        self.stack.store()

        mock_rsc_a = mock.MagicMock(current_template_id=self.stack.t.id)
        mock_rsc_a.name = 'A'
        mock_rsc_b = mock.MagicMock(current_template_id=self.stack.t.id)
        mock_rsc_b.name = 'B'
        mock_db_call.return_value = {
            'A': mock_rsc_a,
            'B': mock_rsc_b
        }

        def get_more(nested_depth=0, filters=None):
            if filters:
                yield 'X'
        mock_nested = self.patchobject(generic_rsrc.StackResourceType,
                                       'nested')
        mock_nested.return_value.iter_resources = mock.MagicMock(
            side_effect=get_more)

        all_resources = list(self.stack.iter_resources(
            nested_depth=1,
            filters=dict(name=['A'])
        ))

        # Verify, the db query is called with expected filter
        mock_db_call.assert_has_calls([
            mock.call(self.ctx, self.stack.id, dict(name=['A'])),
            mock.call(self.ctx, self.stack.id),
        ])

        # Returns three resources (1 first level + 2 second level)
        self.assertEqual(3, len(all_resources))

    def test_load_parent_resource(self):
        self.stack = stack.Stack(self.ctx, 'load_parent_resource', self.tmpl,
                                 parent_resource='parent')
        self.stack.store()
        stk = stack_object.Stack.get_by_id(self.ctx, self.stack.id)

        t = template.Template.load(self.ctx, stk.raw_template_id)
        self.patchobject(template.Template, 'load', return_value=t)

        self.patchobject(stack.Stack, '__init__', return_value=None)

        stack.Stack.load(self.ctx, stack_id=self.stack.id)
        stack.Stack.__init__.assert_called_once_with(
            self.ctx, stk.name, t, stack_id=stk.id,
            action=stk.action, status=stk.status,
            status_reason=stk.status_reason,
            timeout_mins=stk.timeout,
            disable_rollback=stk.disable_rollback,
            parent_resource='parent', owner_id=None,
            stack_user_project_id=None,
            created_time=mock.ANY,
            updated_time=None,
            user_creds_id=stk.user_creds_id,
            tenant_id='test_tenant_id',
            use_stored_context=False,
            username=mock.ANY,
            convergence=False,
            current_traversal=self.stack.current_traversal,
            prev_raw_template_id=None,
            current_deps=None, cache_data=None,
            nested_depth=0,
            deleted_time=None)
        template.Template.load.assert_called_once_with(
            self.ctx, stk.raw_template_id, stk.raw_template)

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
                                 stack_user_project_id='234',
                                 tags=['tag1', 'tag2'])
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
        self.assertEqual(['tag1', 'tag2'], info['tags'])

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
        self.ctx.tenant = 'foobar'
        self.stack = stack.Stack(self.ctx, 'stack_name', self.tmpl)
        self.stack.store()
        stack_id = self.stack.id
        self.ctx.tenant = None
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

    def test_load_all_not_found(self):
        stack1 = stack.Stack(self.ctx, 'stack1', self.tmpl)
        stack1.store()
        tmpl2 = template.Template(copy.deepcopy(empty_template))
        stack2 = stack.Stack(self.ctx, 'stack2', tmpl2)
        stack2.store()

        def fake_load(ctx, template_id, tmpl):
            if template_id == stack2.t.id:
                raise exception.NotFound()
            else:
                return tmpl2

        with mock.patch.object(template.Template, 'load') as tmpl_load:
            tmpl_load.side_effect = fake_load
            stacks = list(stack.Stack.load_all(self.ctx))
            self.assertEqual(1, len(stacks))

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

    def test_update_prev_raw_template(self):
        self.stack = stack.Stack(self.ctx, 'updated_time_test',
                                 self.tmpl)
        self.assertIsNone(self.stack.updated_time)
        self.stack.store()
        self.stack.create()

        self.assertIsNone(self.stack.prev_raw_template_id)

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'R1': {'Type': 'GenericResourceType'}}}
        newstack = stack.Stack(self.ctx, 'updated_time_test',
                               template.Template(tmpl))
        self.stack.update(newstack)
        self.assertIsNotNone(self.stack.prev_raw_template_id)
        prev_t = template.Template.load(self.ctx,
                                        self.stack.prev_raw_template_id)
        self.assertEqual(tmpl, prev_t.t)
        prev_id = self.stack.prev_raw_template_id

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'R2': {'Type': 'GenericResourceType'}}}
        newstack2 = stack.Stack(self.ctx, 'updated_time_test',
                                template.Template(tmpl2))
        self.stack.update(newstack2)
        self.assertIsNotNone(self.stack.prev_raw_template_id)
        self.assertNotEqual(prev_id, self.stack.prev_raw_template_id)
        prev_t2 = template.Template.load(self.ctx,
                                         self.stack.prev_raw_template_id)
        self.assertEqual(tmpl2, prev_t2.t)
        self.assertRaises(exception.NotFound,
                          template.Template.load, self.ctx, prev_id)

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
        self.patchobject(generic_rsrc.GenericResource, 'suspend')

        self.stack.suspend()
        self.assertEqual((self.stack.SUSPEND, self.stack.COMPLETE),
                         self.stack.state)
        generic_rsrc.GenericResource.suspend.assert_not_called()

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
        self.patchobject(generic_rsrc.GenericResource, 'resume')

        self.stack.resume()
        self.assertEqual((self.stack.RESUME, self.stack.COMPLETE),
                         self.stack.state)
        generic_rsrc.GenericResource.resume.assert_not_called()

    def test_suspend_fail(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        exc = Exception('foo')
        self.patchobject(generic_rsrc.GenericResource, 'handle_suspend',
                         side_effect=exc)

        self.stack = stack.Stack(self.ctx, 'suspend_test_fail',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.suspend()

        self.assertEqual((self.stack.SUSPEND, self.stack.FAILED),
                         self.stack.state)
        self.assertEqual('Resource SUSPEND failed: Exception: '
                         'resources.AResource: foo',
                         self.stack.status_reason)
        generic_rsrc.GenericResource.handle_suspend.assert_called_once_with()

    def test_resume_fail(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.patchobject(generic_rsrc.GenericResource, 'handle_resume',
                         side_effect=Exception('foo'))

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
        self.assertEqual('Resource RESUME failed: Exception: '
                         'resources.AResource: foo',
                         self.stack.status_reason)

    def test_suspend_timeout(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        exc = scheduler.Timeout('foo', 0)
        self.patchobject(generic_rsrc.GenericResource, 'handle_suspend',
                         side_effect=exc)

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
        generic_rsrc.GenericResource.handle_suspend.assert_called_once_with()

    def test_resume_timeout(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        exc = scheduler.Timeout('foo', 0)
        self.patchobject(generic_rsrc.GenericResource, 'handle_resume',
                         side_effect=exc)

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
        generic_rsrc.GenericResource.handle_resume.assert_called_once_with()

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
        stack1['A'].state_set(stack1['A'].CREATE, stack1['A'].COMPLETE)
        stack1['B'].state_set(stack1['B'].CREATE, stack1['B'].COMPLETE)
        stack1.check()

        self.assertEqual(stack1.COMPLETE, stack1.status)
        self.assertEqual(stack1.CHECK, stack1.action)
        [self.assertTrue(res.handle_check.called)
         for res in six.itervalues(stack1.resources)]
        self.assertNotIn('not fully supported', stack1.status_reason)

    def test_check_not_supported(self):
        stack1 = self._get_stack_to_check('check-not-supported')
        del stack1['B'].handle_check
        stack1['A'].state_set(stack1['A'].CREATE, stack1['A'].COMPLETE)
        stack1.check()

        self.assertEqual(stack1.COMPLETE, stack1.status)
        self.assertEqual(stack1.CHECK, stack1.action)
        self.assertTrue(stack1['A'].handle_check.called)
        self.assertIn('not fully supported', stack1.status_reason)

    def test_check_fail(self):
        stk = self._get_stack_to_check('check-fail')
        # if resource not created, check fail
        stk.check()
        self.assertEqual(stk.FAILED, stk.status)
        self.assertEqual(stk.CHECK, stk.action)
        self.assertFalse(stk['A'].handle_check.called)
        self.assertFalse(stk['B'].handle_check.called)
        self.assertIn('Resource A not created yet',
                      stk.status_reason)
        self.assertIn('Resource B not created yet',
                      stk.status_reason)
        # check if resource created
        stk['A'].handle_check.side_effect = Exception('fail-A')
        stk['B'].handle_check.side_effect = Exception('fail-B')
        stk['A'].state_set(stk['A'].CREATE, stk['A'].COMPLETE)
        stk['B'].state_set(stk['B'].CREATE, stk['B'].COMPLETE)
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

        loaded_stack = stack.Stack.load(self.ctx, self.stack.id)
        loaded_stack._update_all_resource_data(False, True)
        self.assertEqual('AResource',
                         loaded_stack.outputs['TestOutput'].get_value())
        self.assertIsNone(loaded_stack['AResource']._stored_properties_data)

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
        expected = ('Resource ADOPT failed: Exception: resources.foo: '
                    'Resource ID was not provided.')
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

        for action, status in (
                (rsrc.INIT, rsrc.COMPLETE),
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE),
                (rsrc.CHECK, rsrc.COMPLETE)):
            rsrc.state_set(action, status)
            stk_defn.update_resource_data(self.stack.defn, rsrc.name,
                                          rsrc.node_data())
            self.assertEqual(rsrc, self.stack.resource_by_refid('aaaa'))

        rsrc.state_set(rsrc.DELETE, rsrc.IN_PROGRESS)
        stk_defn.update_resource_data(self.stack.defn, rsrc.name,
                                      rsrc.node_data())
        try:
            self.assertIsNone(self.stack.resource_by_refid('aaaa'))
            self.assertIsNone(self.stack.resource_by_refid('bbbb'))
        finally:
            rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE)

    def test_resource_name_ref_by_depends_on(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'GenericResourceType'},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'AResource'},
                                  'DependsOn': 'AResource'}}}

        self.stack = stack.Stack(self.ctx, 'resource_by_name_ref_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('AResource', self.stack)
        self.assertIn('BResource', self.stack)
        rsrc = self.stack['AResource']
        rsrc.resource_id_set('aaaa')
        b_rsrc = self.stack['BResource']
        b_rsrc.resource_id_set('bbbb')

        b_foo_ref = b_rsrc.properties.get('Foo')

        for action, status in (
                (rsrc.INIT, rsrc.COMPLETE),
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)
            ref_rsrc = self.stack.resource_by_refid(b_foo_ref)
            self.assertEqual(rsrc, ref_rsrc)
            self.assertIn(b_rsrc.name, ref_rsrc.required_by())

    def test_create_failure_recovery(self):
        """Check that rollback still works with dynamic metadata.

        This test fails the second instance.
        """

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'OverwrittenFnGetRefIdType',
                                  'Properties': {'Foo': 'abc'}},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {
                                      'Foo': {'Ref': 'AResource'}}}}}
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)

        class FakeException(Exception):
            # to avoid pep8 check
            pass

        mock_create = self.patchobject(generic_rsrc.ResourceWithFnGetRefIdType,
                                       'handle_create',
                                       side_effect=[FakeException, None])
        mock_delete = self.patchobject(generic_rsrc.ResourceWithFnGetRefIdType,
                                       'handle_delete', return_value=None)

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
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'ID-AResource',
            self.stack['BResource']._stored_properties_data['Foo'])
        mock_delete.assert_called_once_with()
        self.assertEqual(2, mock_create.call_count)

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

        self.patchobject(generic_rsrc.ResourceWithProps,
                         '_update_stored_properties',
                         side_effect=exception.InvalidTemplateAttribute(
                             resource='a', key='foo'))
        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('Resource CREATE failed: The Referenced Attribute '
                         '(a foo) is incorrect.', self.stack.status_reason)

    def test_stack_create_timeout(self):
        def dummy_task():
            while True:
                yield

        self.patchobject(scheduler.DependencyTaskGroup, '__call__',
                         return_value=dummy_task())

        stk = stack.Stack(self.ctx, 's', self.tmpl)
        start_time = time.time()
        self.patchobject(timeutils, 'wallclock',
                         side_effect=[start_time, start_time + 1,
                                      start_time + stk.timeout_secs() + 1])

        stk.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.FAILED), stk.state)
        self.assertEqual('Create timed out', stk.status_reason)
        self.assertEqual(3, timeutils.wallclock.call_count)

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
        gt_255_chars = ('abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz'
                        'abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz'
                        'abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz'
                        'abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz'
                        'abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuv')
        stack_names = ['_foo', '1bad', '.kcats', 'test stack', ' teststack',
                       '^-^', '"stack"', '1234', 'cat|dog', '$(foo)',
                       'test/stack', 'test\\stack', 'test::stack',
                       'test;stack', 'test~stack', '#test', gt_255_chars]
        for stack_name in stack_names:
            ex = self.assertRaises(
                exception.StackValidationFailed, stack.Stack,
                self.ctx, stack_name, self.tmpl)
            self.assertIn("Invalid stack name %s must contain" % stack_name,
                          six.text_type(ex))

    def test_stack_name_invalid_type(self):
        stack_names = [{"bad": 123}, ["no", "lists"]]
        for stack_name in stack_names:
            ex = self.assertRaises(
                exception.StackValidationFailed, stack.Stack,
                self.ctx, stack_name, self.tmpl)
            self.assertIn("Invalid stack name %s, must be a string"
                          % stack_name, six.text_type(ex))

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
                (rsrc.UPDATE, rsrc.COMPLETE),
                (rsrc.DELETE, rsrc.IN_PROGRESS),
                (rsrc.DELETE, rsrc.FAILED),
                (rsrc.DELETE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)
            self.stack._update_all_resource_data(False, True)
            self.assertEqual('AResource',
                             self.stack.outputs['TestOutput'].get_value())

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
        """owner_id attribute of Store is saved to the database when stored."""
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

    def test_tags_property_get_set(self):
        self.stack = stack.Stack(self.ctx, 'stack_tags', self.tmpl)
        self.stack.store()
        stack_id = self.stack.id
        test_stack = stack.Stack.load(self.ctx, stack_id=stack_id)
        self.assertIsNone(test_stack.tags)

        self.stack = stack.Stack(self.ctx, 'stack_name', self.tmpl)
        self.stack.tags = ['tag1', 'tag2']
        self.assertEqual(['tag1', 'tag2'], self.stack._tags)
        self.stack.store()
        stack_id = self.stack.id
        test_stack = stack.Stack.load(self.ctx, stack_id=stack_id)
        self.assertIsNone(test_stack._tags)
        self.assertEqual(['tag1', 'tag2'], test_stack.tags)
        self.assertEqual(['tag1', 'tag2'], test_stack._tags)

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
        """A user_creds entry is created on first stack store."""
        cfg.CONF.set_default('deferred_auth_method', 'password')
        self.stack = stack.Stack(self.ctx, 'creds_stack', self.tmpl)
        self.stack.store()

        # The store should've created a user_creds row and set user_creds_id
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        user_creds_id = db_stack.user_creds_id
        self.assertIsNotNone(user_creds_id)

        # should've stored the username/password in the context
        user_creds = ucreds_object.UserCreds.get_by_id(self.ctx, user_creds_id)
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
        """A user_creds entry is created on first stack store."""
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self.patchobject(keystone.KeystoneClientPlugin, '_create',
                         return_value=fake_ks.FakeKeystoneClient(
                             user_id='auser123'))

        self.stack = stack.Stack(self.ctx, 'creds_stack', self.tmpl)
        self.stack.store()

        # The store should've created a user_creds row and set user_creds_id
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        user_creds_id = db_stack.user_creds_id
        self.assertIsNotNone(user_creds_id)

        # should've stored the trust_id and trustor_user_id returned from
        # FakeKeystoneClient.create_trust_context, username/password should
        # not have been stored
        user_creds = ucreds_object.UserCreds.get_by_id(self.ctx, user_creds_id)
        self.assertIsNone(user_creds.get('username'))
        self.assertIsNone(user_creds.get('password'))
        self.assertEqual('atrust', user_creds.get('trust_id'))
        self.assertEqual('auser123', user_creds.get('trustor_user_id'))

        auth = self.patchobject(context.RequestContext,
                                'trusts_auth_plugin')
        self.patchobject(auth, 'get_access',
                         return_value=fakes.FakeAccessInfo([], None, None))

        # Check the stored_context is as expected
        expected_context = context.RequestContext(
            trust_id='atrust', trustor_user_id='auser123',
            request_id=self.ctx.request_id, is_admin=False).to_dict()
        stored_context = self.stack.stored_context().to_dict()
        self.assertEqual(expected_context, stored_context)

        # Store again, ID should not change
        self.stack.store()
        self.assertEqual(user_creds_id, db_stack.user_creds_id)
        keystone.KeystoneClientPlugin._create.assert_called_with()

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
        """Test stored_context error path."""
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
        """Loading a stack from the database will set the owner_id.

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

    def test_stack_user_project_id_setter(self):
        self.stub_keystoneclient()

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

    def test_stack_user_project_id_create(self):
        self.stub_keystoneclient()

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

    def test_stack_eager_or_lazy_load_templ(self):
        self.stack = stack.Stack(self.ctx, 'test_stack_eager_or_lazy_tmpl',
                                 self.tmpl)
        self.stack.store()

        ctx1 = utils.dummy_context()
        s1_db_result = db_api.stack_get(ctx1, self.stack.id, eager_load=True)
        s1_obj = stack_object.Stack._from_db_object(ctx1, stack_object.Stack(),
                                                    s1_db_result)
        self.assertIsNotNone(s1_obj._raw_template)
        self.assertIsNotNone(s1_obj.raw_template)

        ctx2 = utils.dummy_context()
        s2_db_result = db_api.stack_get(ctx2, self.stack.id, eager_load=False)
        s2_obj = stack_object.Stack._from_db_object(ctx2, stack_object.Stack(),
                                                    s2_db_result)
        # _raw_template has not been set since it not eagerly loaded
        self.assertFalse(hasattr(s2_obj, "_raw_template"))
        # accessing raw_template lazy loads it
        self.assertIsNotNone(s2_obj.raw_template)
        self.assertIsNotNone(s2_obj._raw_template)

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
        self.stack._update_all_resource_data(False, True)
        self.assertEqual('AResource',
                         self.stack.outputs['Resource_attr'].get_value())

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

        ex = self.assertRaises(exception.InvalidTemplateAttribute,
                               self.stack.outputs['Resource_attr'].get_value)
        self.assertIn('The Referenced Attribute (AResource Bar) is '
                      'incorrect.',
                      six.text_type(ex))

        self.stack.delete()

        self.assertEqual((self.stack.DELETE, self.stack.COMPLETE),
                         self.stack.state)

    def test_stack_load_no_param_value_validation(self):
        """Test stack loading with disabled parameter value validation."""
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
        self.patchobject(nova.NovaClientPlugin, 'client', return_value=fc)

        fc.flavors = mock.Mock()
        flavor = collections.namedtuple("Flavor", ["id", "name"])
        flavor.id = "1234"
        flavor.name = "dummy"
        fc.flavors.get.return_value = flavor

        test_env = environment.Environment({'flavor': '1234'})
        self.stack = stack.Stack(self.ctx, 'stack_with_custom_constraint',
                                 template.Template(tmpl, env=test_env))

        self.stack.validate()
        self.stack.store()
        self.stack.create()
        stack_id = self.stack.id

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        loaded_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(stack_id, loaded_stack.parameters['OS::stack_id'])
        fc.flavors.get.assert_called_once_with('1234')

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

        self.assertRaisesRegex(
            exception.StackValidationFailed,
            ('Outputs.Resource_attr.Value.Fn::GetAtt: The Referenced '
             r'Attribute \(AResource Bar\) is incorrect.'),
            self.stack.validate)

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

    def test_incorrect_outputs_cfn_missing_value(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Resources:
          AResource:
            Type: ResourceWithPropsType
            Properties:
              Foo: abc
        Outputs:
          Resource_attr:
            Description: the attr
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('Each output definition must contain a Value key.',
                      six.text_type(ex))
        self.assertIn('Outputs.Resource_attr', six.text_type(ex))

    def test_incorrect_outputs_cfn_empty_value(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Resources:
          AResource:
            Type: ResourceWithPropsType
            Properties:
              Foo: abc
        Outputs:
          Resource_attr:
            Value: ''
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        self.assertIsNone(self.stack.validate())

    def test_incorrect_outputs_cfn_none_value(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Resources:
          AResource:
            Type: ResourceWithPropsType
            Properties:
              Foo: abc
        Outputs:
          Resource_attr:
            Value:
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_correct_outputs',
                                 template.Template(tmpl))

        self.assertIsNone(self.stack.validate())

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

        self.assertIn('Found a %s instead' % six.text_type.__name__,
                      six.text_type(ex))
        self.assertIn('Outputs.Resource_attr', six.text_type(ex))

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

    def test_disable_validate_required_param(self):
        tmpl = template_format.parse("""
        heat_template_version: 2013-05-23
        parameters:
          aparam:
            type: number
        resources:
          AResource:
            type: ResourceWithPropsRefPropOnValidate
            properties:
              FooInt: {get_param: aparam}
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_reqd_param',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.UserParameterMissing,
                               self.stack.validate)
        self.assertIn("The Parameter (aparam) was not provided",
                      six.text_type(ex))

        self.stack.strict_validate = False
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)
        self.assertIn("The Parameter (aparam) was not provided",
                      six.text_type(ex))

        self.assertIsNone(self.stack.validate(validate_res_tmpl_only=True))

    def test_nodisable_validate_tmpl_err(self):
        tmpl = template_format.parse("""
        heat_template_version: 2013-05-23
        resources:
          AResource:
            type: ResourceWithPropsRefPropOnValidate
            depends_on: noexist
            properties:
              FooInt: 123
        """)
        self.stack = stack.Stack(self.ctx, 'stack_with_tmpl_err',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.InvalidTemplateReference,
                               self.stack.validate)
        self.assertIn(
            "The specified reference \"noexist\" (in AResource) is incorrect",
            six.text_type(ex))

        self.stack.strict_validate = False
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               self.stack.validate)
        self.assertIn(
            "The specified reference \"noexist\" (in AResource) is incorrect",
            six.text_type(ex))

        ex = self.assertRaises(exception.InvalidTemplateReference,
                               self.stack.validate,
                               validate_res_tmpl_only=True)
        self.assertIn(
            "The specified reference \"noexist\" (in AResource) is incorrect",
            six.text_type(ex))

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

        self.assertIn("Parameter 'foo' is invalid: could not convert "
                      "string to float:", six.text_type(ex))
        self.assertIn("abc", six.text_type(ex))

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

        self.assertIn('Found a list', six.text_type(ex))
        self.assertIn('Outputs.Resource_attr', six.text_type(ex))

    def test_incorrect_deletion_policy(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Parameters:
          Deletion_Policy:
            Type: String
            Default: [1, 2]
        Resources:
          AResource:
            Type: ResourceWithPropsType
            DeletionPolicy: {Ref: Deletion_Policy}
            Properties:
              Foo: abc
        """)

        self.stack = stack.Stack(self.ctx, 'stack_bad_delpol',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('Invalid deletion policy "[1, 2]"',
                      six.text_type(ex))

    def test_deletion_policy_apply_ref(self):
        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Parameters:
          Deletion_Policy:
            Type: String
            Default: Delete
        Resources:
          AResource:
            Type: ResourceWithPropsType
            DeletionPolicy: wibble
            Properties:
              Foo: abc
            DeletionPolicy: {Ref: Deletion_Policy}
        """)

        self.stack = stack.Stack(self.ctx, 'stack_delpol_get_param',
                                 template.Template(tmpl))
        self.stack.validate()
        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

    def test_deletion_policy_apply_get_param(self):
        tmpl = template_format.parse("""
        heat_template_version: 2016-04-08
        parameters:
          deletion_policy:
            type: string
            default: Delete
        resources:
          AResource:
            type: ResourceWithPropsType
            deletion_policy: {get_param: deletion_policy}
            properties:
              Foo: abc
        """)

        self.stack = stack.Stack(self.ctx, 'stack_delpol_get_param',
                                 template.Template(tmpl))
        self.stack.validate()
        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

    def test_incorrect_deletion_policy_hot(self):
        tmpl = template_format.parse("""
        heat_template_version: 2013-05-23
        parameters:
          deletion_policy:
            type: string
            default: [1, 2]
        resources:
          AResource:
            type: ResourceWithPropsType
            deletion_policy: {get_param: deletion_policy}
            properties:
              Foo: abc
        """)
        self.stack = stack.Stack(self.ctx, 'stack_bad_delpol',
                                 template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertIn('Invalid deletion policy "[1, 2]',
                      six.text_type(ex))

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

        self.assertRaisesRegex(
            exception.StackValidationFailed,
            ('outputs.resource_attr.value.get_attr: The Referenced Attribute '
             r'\(AResource Bar\) is incorrect.'),
            self.stack.validate)

    def test_snapshot_save_called_first(self):
        def snapshotting_called_first(stack, action, status, reason):
            self.assertEqual(stack.status, stack.IN_PROGRESS)
            self.assertEqual(stack.action, stack.SNAPSHOT)

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'A': {'Type': 'GenericResourceType'},
                    'B': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'stack_details_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.stack.snapshot(save_snapshot_func=snapshotting_called_first)

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

        tpl = {'heat_template_version': '2013-05-23',
               'resources':
               {'A': {'type': 'ResourceWithRestoreType'}}}
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

        rsrcs_data = {'foo': {'reference_id': 'foo-id',
                              'attrs': {'bar': 'baz'}, 'uuid': mock.ANY,
                              'id': mock.ANY, 'action': 'CREATE',
                              'status': 'COMPLETE'},
                      'bar': {'reference_id': 'bar-id', 'uuid': mock.ANY,
                              'id': mock.ANY, 'action': 'CREATE',
                              'status': 'COMPLETE'}}
        cache_data = {n: node_data.NodeData.from_dict(d)
                      for n, d in rsrcs_data.items()}
        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl)
        tmpl_stack.store()
        lightweight_stack = stack.Stack.load(self.ctx, stack_id=tmpl_stack.id,
                                             cache_data=cache_data)

        # Check if the property has the appropriate resolved value.
        bar = resource.Resource(
            'bar',
            lightweight_stack.defn.resource_definition('bar'),
            lightweight_stack)
        self.assertEqual('baz', bar.properties['Foo'])

        # Make sure FnGetAtt returns the cached value.
        attr_value = lightweight_stack.defn['foo'].FnGetAtt('bar')
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

        rsrcs_data = {'foo': {'reference_id': 'physical-resource-id',
                              'uuid': mock.ANY, 'id': mock.ANY,
                              'action': 'CREATE', 'status': 'COMPLETE'},
                      'bar': {'reference_id': 'bar-id', 'uuid': mock.ANY,
                              'id': mock.ANY, 'action': 'CREATE',
                              'status': 'COMPLETE'}}
        cache_data = {n: node_data.NodeData.from_dict(d)
                      for n, d in rsrcs_data.items()}
        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl)
        tmpl_stack.store()
        lightweight_stack = stack.Stack.load(self.ctx, stack_id=tmpl_stack.id,
                                             cache_data=cache_data)

        # Check if the property has the appropriate resolved value.
        bar = resource.Resource(
            'bar',
            lightweight_stack.defn.resource_definition('bar'),
            lightweight_stack)
        self.assertEqual('physical-resource-id', bar.properties['Foo'])

        # Make sure FnGetRefId returns the cached value.
        resource_id = lightweight_stack.defn['foo'].FnGetRefId()
        self.assertEqual('physical-resource-id', resource_id)

        # Make sure calls are not made to the database to retrieve the
        # resource state.
        self.assertFalse(mock_drg.called)

    def test_encrypt_parameters_false_parameters_stored_plaintext(self):
        """Test stack loading with disabled parameter value validation."""
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
        """Test stack loading with disabled parameter value validation."""
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
        self.assertEqual('cryptography_decrypt_v1', db_params['param2'][0])
        self.assertIsNotNone(db_params['param2'][1])

        # Verify that loaded stack has decrypted paramters
        loaded_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        params = loaded_stack.t.env.params
        self.assertEqual('foo', params.get('param1'))
        self.assertEqual('bar', params.get('param2'))

        # test update the param2
        loaded_stack.state_set(self.stack.CREATE, self.stack.COMPLETE,
                               'for_update')
        env2 = environment.Environment({'param1': 'foo', 'param2': 'new_bar'})
        new_stack = stack.Stack(self.ctx, 'test_update',
                                template.Template(tmpl, env=env2))

        loaded_stack.update(new_stack)
        self.assertEqual((loaded_stack.UPDATE, loaded_stack.COMPLETE),
                         loaded_stack.state)
        db_tpl = db_api.raw_template_get(self.ctx, loaded_stack.t.id)
        db_params = db_tpl.environment['parameters']
        self.assertEqual('foo', db_params['param1'])
        self.assertEqual('cryptography_decrypt_v1', db_params['param2'][0])
        self.assertIsNotNone(db_params['param2'][1])

        loaded_stack1 = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        params = loaded_stack1.t.env.params
        self.assertEqual('foo', params.get('param1'))
        self.assertEqual('new_bar', params.get('param2'))

    def test_parameters_created_encrypted_updated_decrypted(self):
        """Test stack loading with disabled parameter value validation."""
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

        # Create the stack with encryption enabled
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)
        env1 = environment.Environment({'param1': 'foo', 'param2': 'bar'})
        self.stack = stack.Stack(self.ctx, 'test',
                                 template.Template(tmpl, env=env1))
        self.stack.store()

        # Update the stack with encryption disabled
        cfg.CONF.set_override('encrypt_parameters_and_properties', False)
        loaded_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        loaded_stack.state_set(self.stack.CREATE, self.stack.COMPLETE,
                               'for_update')
        env2 = environment.Environment({'param1': 'foo', 'param2': 'new_bar'})
        new_stack = stack.Stack(self.ctx, 'test_update',
                                template.Template(tmpl, env=env2))

        self.assertEqual(['param2'], loaded_stack.env.encrypted_param_names)

        # Without the fix for bug #1572294, loaded_stack.update() will
        # blow up with "ValueError: too many values to unpack"
        loaded_stack.update(new_stack)

        self.assertEqual([], loaded_stack.env.encrypted_param_names)

    def test_parameters_inconsistent_encrypted_param_names(self):
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
        warning_logger = self.useFixture(
            fixtures.FakeLogger(level=logging.WARNING,
                                format="%(levelname)8s [%(name)s] "
                                       "%(message)s"))

        cfg.CONF.set_override('encrypt_parameters_and_properties', False)

        env1 = environment.Environment({'param1': 'foo', 'param2': 'bar'})
        self.stack = stack.Stack(self.ctx, 'test',
                                 template.Template(tmpl, env=env1))
        self.stack.store()

        loaded_stack = stack.Stack.load(self.ctx, stack_id=self.stack.id)
        loaded_stack.state_set(self.stack.CREATE, self.stack.COMPLETE,
                               'for_update')

        env2 = environment.Environment({'param1': 'foo', 'param2': 'new_bar'})

        # Put inconsistent encrypted_param_names data in the environment
        env2.encrypted_param_names = ['param1']
        new_stack = stack.Stack(self.ctx, 'test_update',
                                template.Template(tmpl, env=env2))
        self.assertIsNone(loaded_stack.update(new_stack))
        self.assertIn('Encountered already-decrypted data',
                      warning_logger.output)

    def test_parameters_stored_decrypted_successful_load(self):
        """Test stack loading with disabled parameter value validation."""
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

    def test_event_dispatch(self):
        env = environment.Environment()
        evt = eventlet.event.Event()
        sink = fakes.FakeEventSink(evt)
        env.register_event_sink('dummy', lambda: sink)
        env.load({"event_sinks": [{"type": "dummy"}]})
        stk = stack.Stack(self.ctx, 'test',
                          template.Template(empty_template, env=env))
        stk.thread_group_mgr = service.ThreadGroupManager()
        self.addCleanup(stk.thread_group_mgr.stop, stk.id)
        stk.store()
        stk._add_event('CREATE', 'IN_PROGRESS', '')
        evt.wait()
        expected = [{
            'id': mock.ANY,
            'timestamp': mock.ANY,
            'type': 'os.heat.event',
            'version': '0.1',
            'payload': {
                'physical_resource_id': stk.id,
                'resource_action': 'CREATE',
                'resource_name': 'test',
                'resource_properties': {},
                'resource_status': 'IN_PROGRESS',
                'resource_status_reason': '',
                'resource_type':
                'OS::Heat::Stack',
                'stack_id': stk.id,
                'version': '0.1'}}]
        self.assertEqual(expected, sink.events)

    @mock.patch.object(stack_object.Stack, 'delete')
    @mock.patch.object(raw_template_object.RawTemplate, 'delete')
    def test_mark_complete_create(self, mock_tmpl_delete, mock_stack_delete):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })

        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl, convergence=True)
        tmpl_stack.store()
        tmpl_stack.action = tmpl_stack.CREATE
        tmpl_stack.status = tmpl_stack.IN_PROGRESS
        tmpl_stack.current_traversal = 'some-traversal'
        tmpl_stack.mark_complete()
        self.assertEqual(tmpl_stack.prev_raw_template_id,
                         None)
        self.assertFalse(mock_tmpl_delete.called)
        self.assertFalse(mock_stack_delete.called)
        self.assertEqual(tmpl_stack.status, tmpl_stack.COMPLETE)

    @mock.patch.object(stack.Stack, 'purge_db')
    def test_mark_complete_update(self, mock_purge_db):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })

        cfg.CONF.set_default('convergence_engine', True)
        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl, convergence=True)
        tmpl_stack.prev_raw_template_id = 1
        tmpl_stack.action = tmpl_stack.UPDATE
        tmpl_stack.status = tmpl_stack.IN_PROGRESS
        tmpl_stack.current_traversal = 'some-traversal'
        tmpl_stack.store()
        tmpl_stack.mark_complete()
        self.assertTrue(mock_purge_db.called)

    @mock.patch.object(stack.Stack, 'purge_db')
    def test_mark_complete_update_delete(self, mock_purge_db):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Description': 'Empty Template'
        })

        cfg.CONF.set_default('convergence_engine', True)
        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl, convergence=True)
        tmpl_stack.prev_raw_template_id = 1
        tmpl_stack.action = tmpl_stack.DELETE
        tmpl_stack.status = tmpl_stack.IN_PROGRESS
        tmpl_stack.current_traversal = 'some-traversal'
        tmpl_stack.store()
        tmpl_stack.mark_complete()
        self.assertTrue(mock_purge_db.called)

    @mock.patch.object(stack.Stack, 'purge_db')
    def test_mark_complete_stale_traversal(self, mock_purge_db):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })

        tmpl_stack = stack.Stack(self.ctx, 'test', tmpl)
        tmpl_stack.store()
        # emulate stale traversal
        tmpl_stack.current_traversal = 'old-traversal'
        tmpl_stack.mark_complete()
        self.assertFalse(mock_purge_db.called)

    @mock.patch.object(function, 'validate')
    def test_validate_assertion_exception_rethrow(self, func_val):
        expected_msg = 'Expected Assertion Error'
        with mock.patch('heat.engine.stack.dependencies',
                        new_callable=mock.PropertyMock) as mock_dependencies:
            mock_dependency = mock.MagicMock()
            mock_dependency.name = 'res'
            mock_dependency.external_id = None
            mock_dependency.validate.side_effect = AssertionError(expected_msg)
            mock_dependencies.Dependencies.return_value = [mock_dependency]
            stc = stack.Stack(self.ctx, utils.random_name(), self.tmpl)
            mock_res = mock.Mock()
            mock_res.name = mock_dependency.name
            mock_res.t = mock.Mock()
            mock_res.t.name = mock_res.name
            stc._resources = {mock_res.name: mock_res}
            expected_exception = self.assertRaises(AssertionError,
                                                   stc.validate)
            self.assertEqual(expected_msg, six.text_type(expected_exception))
            mock_dependency.validate.assert_called_once_with()

        tmpl = template_format.parse("""
        HeatTemplateFormatVersion: '2012-12-12'
        Outputs:
          foo:
            Value: bar
        """)
        stc = stack.Stack(self.ctx, utils.random_name(),
                          template.Template(tmpl))
        func_val.side_effect = AssertionError(expected_msg)
        expected_exception = self.assertRaises(AssertionError, stc.validate)
        self.assertEqual(expected_msg, six.text_type(expected_exception))

    @mock.patch.object(update, 'StackUpdate')
    def test_update_task_exception(self, mock_stack_update):
        class RandomException(Exception):
            pass

        tmpl1 = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })
        self.stack = stack.Stack(utils.dummy_context(), 'test_stack', tmpl1)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {'Type': 'GenericResourceType'}
            }
        })
        updated_stack = stack.Stack(utils.dummy_context(), 'test_stack', tmpl2)

        mock_stack_update.side_effect = RandomException()
        self.assertRaises(RandomException, self.stack.update, updated_stack)

    def update_exception_handler(self, exc, action=stack.Stack.UPDATE,
                                 disable_rollback=False):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })
        self.stack = stack.Stack(utils.dummy_context(),
                                 'test_stack',
                                 tmpl,
                                 disable_rollback=disable_rollback)
        self.stack.store()

        rb = self.stack._update_exception_handler(exc=exc, action=action)

        return rb

    def test_update_exception_handler_resource_failure_no_rollback(self):
        reason = 'something strange happened'
        exc = exception.ResourceFailure(reason, None, action='UPDATE')
        rb = self.update_exception_handler(exc, disable_rollback=True)
        self.assertFalse(rb)

    def test_update_exception_handler_resource_failure_rollback(self):
        reason = 'something strange happened'
        exc = exception.ResourceFailure(reason, None, action='UPDATE')
        rb = self.update_exception_handler(exc, disable_rollback=False)
        self.assertTrue(rb)

    def test_update_exception_handler_force_cancel_with_rollback(self):
        exc = stack.ForcedCancel(with_rollback=True)
        rb = self.update_exception_handler(exc, disable_rollback=False)
        self.assertTrue(rb)

    def test_update_exception_handler_force_cancel_with_rollback_off(self):
        # stack-cancel-update from user *always* rolls back
        exc = stack.ForcedCancel(with_rollback=True)
        rb = self.update_exception_handler(exc, disable_rollback=True)
        self.assertTrue(rb)

    def test_update_exception_handler_force_cancel_nested(self):
        exc = stack.ForcedCancel(with_rollback=False)
        rb = self.update_exception_handler(exc, disable_rollback=True)
        self.assertFalse(rb)

    def test_store_generates_new_traversal_id_for_new_stack(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })
        self.stack = stack.Stack(utils.dummy_context(),
                                 'test_stack', tmpl, convergence=True)
        self.assertIsNone(self.stack.current_traversal)
        self.stack.store()
        self.assertIsNotNone(self.stack.current_traversal)

    @mock.patch.object(stack_object.Stack, 'select_and_update')
    def test_store_uses_traversal_id_for_updating_db(self, mock_sau):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })
        self.stack = stack.Stack(utils.dummy_context(),
                                 'test_stack', tmpl, convergence=True)
        mock_sau.return_value = True
        self.stack.id = 1
        self.stack.current_traversal = 1
        stack_id = self.stack.store()
        mock_sau.assert_called_once_with(mock.ANY, 1, mock.ANY, exp_trvsl=1)
        self.assertEqual(1, stack_id)

        # ensure store uses given expected traversal ID
        stack_id = self.stack.store(exp_trvsl=2)
        self.assertEqual(1, stack_id)
        mock_sau.assert_called_with(mock.ANY, 1, mock.ANY, exp_trvsl=2)

    @mock.patch.object(stack_object.Stack, 'select_and_update')
    def test_store_db_update_failure(self, mock_sau):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })
        self.stack = stack.Stack(utils.dummy_context(),
                                 'test_stack', tmpl, convergence=True)
        mock_sau.return_value = False
        self.stack.id = 1
        stack_id = self.stack.store()
        self.assertIsNone(stack_id)

    @mock.patch.object(stack_object.Stack, 'select_and_update')
    def test_state_set_uses_curr_traversal_for_updating_db(self, mock_sau):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'}
            }
        })
        self.stack = stack.Stack(utils.dummy_context(),
                                 'test_stack', tmpl, convergence=True)
        self.stack.id = 1
        self.stack.current_traversal = 'curr-traversal'
        self.stack.store()
        self.stack.state_set(self.stack.UPDATE, self.stack.IN_PROGRESS, '')
        mock_sau.assert_called_once_with(mock.ANY, 1, mock.ANY,
                                         exp_trvsl='curr-traversal')


class StackKwargsForCloningTest(common.HeatTestCase):
    scenarios = [
        ('default', dict(keep_status=False, only_db=False, keep_tags=False,
                         not_included=['action', 'status', 'status_reason',
                                       'tags'])),
        ('only_db', dict(keep_status=False, only_db=True, keep_tags=False,
                         not_included=['action', 'status', 'status_reason',
                                       'strict_validate', 'tags'])),
        ('keep_status', dict(keep_status=True, only_db=False, keep_tags=False,
                             not_included=['tags'])),
        ('status_db', dict(keep_status=True, only_db=True, keep_tags=False,
                           not_included=['strict_validate', 'tags'])),
        ('keep_tags', dict(keep_status=False, only_db=False, keep_tags=True,
                           not_included=['action', 'status', 'status_reason']))
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
                         current_traversal=45,
                         tags=['tag1', 'tag2'])
        db_map = {'parent_resource': 'parent_resource_name',
                  'tenant_id': 'tenant', 'timeout_mins': 'timeout'}
        test_db_data = {}
        for key in test_data:
            dbkey = db_map.get(key, key)
            test_db_data[dbkey] = test_data[key]

        self.stack = stack.Stack(ctx, utils.random_name(), tmpl,
                                 **test_data)
        res = self.stack.get_kwargs_for_cloning(keep_status=self.keep_status,
                                                only_db=self.only_db,
                                                keep_tags=self.keep_tags)
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


class ResetStateOnErrorTest(common.HeatTestCase):
    class DummyStack(object):

        (COMPLETE, IN_PROGRESS, FAILED) = range(3)
        action = 'something'
        status = COMPLETE

        def __init__(self):
            self.mark_failed = mock.MagicMock()
            self.convergence = False

        @stack.reset_state_on_error
        def raise_exception(self):
            self.status = self.IN_PROGRESS
            raise ValueError('oops')

        @stack.reset_state_on_error
        def raise_exit_exception(self):
            self.status = self.IN_PROGRESS
            raise BaseException('bye')

        @stack.reset_state_on_error
        def succeed(self):
            return 'Hello world'

        @stack.reset_state_on_error
        def fail(self):
            self.status = self.FAILED
            return 'Hello world'

    def test_success(self):
        dummy = self.DummyStack()

        self.assertEqual('Hello world', dummy.succeed())
        self.assertFalse(dummy.mark_failed.called)

    def test_failure(self):
        dummy = self.DummyStack()

        self.assertEqual('Hello world', dummy.fail())
        self.assertFalse(dummy.mark_failed.called)

    def test_reset_state_exception(self):
        dummy = self.DummyStack()

        exc = self.assertRaises(ValueError, dummy.raise_exception)
        self.assertIn('oops', str(exc))
        self.assertTrue(dummy.mark_failed.called)

    def test_reset_state_exit_exception(self):
        dummy = self.DummyStack()

        exc = self.assertRaises(BaseException, dummy.raise_exit_exception)
        self.assertIn('bye', str(exc))
        self.assertTrue(dummy.mark_failed.called)


class StackStateSetTest(common.HeatTestCase):
    scenarios = [
        ('in_progress', dict(action=stack.Stack.CREATE,
                             status=stack.Stack.IN_PROGRESS,
                             persist_count=1, error=False)),
        ('create_complete', dict(action=stack.Stack.CREATE,
                                 status=stack.Stack.COMPLETE,
                                 persist_count=0, error=False)),
        ('create_failed', dict(action=stack.Stack.CREATE,
                               status=stack.Stack.FAILED,
                               persist_count=0, error=False)),
        ('update_complete', dict(action=stack.Stack.UPDATE,
                                 status=stack.Stack.COMPLETE,
                                 persist_count=1, error=False)),
        ('update_failed', dict(action=stack.Stack.UPDATE,
                               status=stack.Stack.FAILED,
                               persist_count=1, error=False)),
        ('delete_complete', dict(action=stack.Stack.DELETE,
                                 status=stack.Stack.COMPLETE,
                                 persist_count=1, error=False)),
        ('delete_failed', dict(action=stack.Stack.DELETE,
                               status=stack.Stack.FAILED,
                               persist_count=1, error=False)),
        ('adopt_complete', dict(action=stack.Stack.ADOPT,
                                status=stack.Stack.COMPLETE,
                                persist_count=0, error=False)),
        ('adopt_failed', dict(action=stack.Stack.ADOPT,
                              status=stack.Stack.FAILED,
                              persist_count=0, error=False)),
        ('rollback_complete', dict(action=stack.Stack.ROLLBACK,
                                   status=stack.Stack.COMPLETE,
                                   persist_count=1, error=False)),
        ('rollback_failed', dict(action=stack.Stack.ROLLBACK,
                                 status=stack.Stack.FAILED,
                                 persist_count=1, error=False)),
        ('invalid_action', dict(action='action',
                                status=stack.Stack.FAILED,
                                persist_count=0, error=True)),
        ('invalid_status', dict(action=stack.Stack.CREATE,
                                status='status',
                                persist_count=0, error=True)),

    ]

    def test_state(self):
        self.tmpl = template.Template(copy.deepcopy(empty_template))
        self.ctx = utils.dummy_context()
        self.stack = stack.Stack(self.ctx, 'test_stack', self.tmpl,
                                 action=stack.Stack.CREATE,
                                 status=stack.Stack.IN_PROGRESS)
        persist_state = self.patchobject(self.stack, '_persist_state')
        self.assertEqual((stack.Stack.CREATE, stack.Stack.IN_PROGRESS),
                         self.stack.state)
        if self.error:
            self.assertRaises(ValueError, self.stack.state_set,
                              self.action, self.status, 'test')
        else:
            self.stack.state_set(self.action, self.status, 'test')
            self.assertEqual((self.action, self.status), self.stack.state)
            self.assertEqual('test', self.stack.status_reason)
        self.assertEqual(self.persist_count, persist_state.call_count)
