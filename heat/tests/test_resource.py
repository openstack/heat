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

import itertools
import json
import uuid

import mock
from oslo.config import cfg
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import short_id
from heat.common import timeutils
from heat.db import api as db_api
from heat.engine import attributes
from heat.engine.cfn import functions as cfn_funcs
from heat.engine import dependencies
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

import neutronclient.common.exceptions as neutron_exp


empty_template = {"HeatTemplateFormatVersion": "2012-12-12"}


class ResourceTest(HeatTestCase):
    def setUp(self):
        super(ResourceTest, self).setUp()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithCustomConstraint',
                                 generic_rsrc.ResourceWithCustomConstraint)

        self.env = environment.Environment()
        self.env.load({u'resource_registry':
                      {u'OS::Test::GenericResource': u'GenericResourceType',
                       u'OS::Test::ResourceWithCustomConstraint':
                       u'ResourceWithCustomConstraint'}})

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  parser.Template(empty_template),
                                  env=self.env, stack_id=str(uuid.uuid4()))
        self.patch('heat.engine.resource.warnings')

    def test_get_class_ok(self):
        cls = resource.get_class('GenericResourceType')
        self.assertEqual(generic_rsrc.GenericResource, cls)

    def test_get_class_noexist(self):
        self.assertRaises(exception.StackValidationFailed, resource.get_class,
                          'NoExistResourceType')

    def test_resource_new_ok(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        res = resource.Resource('aresource', snippet, self.stack)
        self.assertIsInstance(res, generic_rsrc.GenericResource)
        self.assertEqual("INIT", res.action)

    def test_resource_new_stack_not_stored(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        self.stack.id = None
        db_method = 'resource_get_by_name_and_stack'
        with mock.patch.object(db_api, db_method) as resource_get:
            res = resource.Resource('aresource', snippet, self.stack)
            self.assertEqual("INIT", res.action)
            self.assertIs(False, resource_get.called)

    def test_resource_new_err(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'NoExistResourceType')
        self.assertRaises(exception.StackValidationFailed,
                          resource.Resource, 'aresource', snippet, self.stack)

    def test_resource_non_type(self):
        resource_name = 'aresource'
        snippet = rsrc_defn.ResourceDefinition(resource_name, '')
        ex = self.assertRaises(exception.StackValidationFailed,
                               resource.Resource, resource_name,
                               snippet, self.stack)
        self.assertIn(_('Resource "%s" has no type') % resource_name,
                      six.text_type(ex))

    def test_state_defaults(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_def', 'Foo')
        res = generic_rsrc.GenericResource('test_res_def', tmpl, self.stack)
        self.assertEqual((res.INIT, res.COMPLETE), res.state)
        self.assertEqual('', res.status_reason)

    def test_resource_str_repr_stack_id_resource_id(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_str_repr', 'Foo')
        res = generic_rsrc.GenericResource('test_res_str_repr', tmpl,
                                           self.stack)
        res.stack.id = "123"
        res.resource_id = "456"
        expected = ('GenericResource "test_res_str_repr" [456] Stack '
                    '"test_stack" [123]')
        observed = str(res)
        self.assertEqual(expected, observed)

    def test_resource_str_repr_stack_id_no_resource_id(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_str_repr', 'Foo')
        res = generic_rsrc.GenericResource('test_res_str_repr', tmpl,
                                           self.stack)
        res.stack.id = "123"
        res.resource_id = None
        expected = ('GenericResource "test_res_str_repr" Stack "test_stack" '
                    '[123]')
        observed = str(res)
        self.assertEqual(expected, observed)

    def test_resource_str_repr_no_stack_id(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_str_repr', 'Foo')
        res = generic_rsrc.GenericResource('test_res_str_repr', tmpl,
                                           self.stack)
        res.stack.id = None
        expected = ('GenericResource "test_res_str_repr"')
        observed = str(res)
        self.assertEqual(expected, observed)

    def test_state_set(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.state_set(res.CREATE, res.COMPLETE, 'wibble')
        self.assertEqual(res.CREATE, res.action)
        self.assertEqual(res.COMPLETE, res.status)
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        self.assertEqual('wibble', res.status_reason)

    def test_physical_resource_name_or_FnGetRefId(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        # use physical_resource_name when res.id is not None
        self.assertIsNotNone(res.id)
        expected = '%s-%s-%s' % (self.stack.name,
                                 res.name,
                                 short_id.get_id(res.id))
        self.assertEqual(expected, res.physical_resource_name_or_FnGetRefId())

        # otherwise use parent method
        res.id = None
        self.assertIsNone(res.resource_id)
        self.assertEqual('test_resource',
                         res.physical_resource_name_or_FnGetRefId())

    def test_prepare_abandon(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        expected = {
            'action': 'INIT',
            'metadata': {},
            'name': 'test_resource',
            'resource_data': {},
            'resource_id': None,
            'status': 'COMPLETE',
            'type': 'Foo'
        }
        actual = res.prepare_abandon()
        self.assertEqual(expected, actual)

    def test_abandon_with_resource_data(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res._data = {"test-key": "test-value"}

        expected = {
            'action': 'INIT',
            'metadata': {},
            'name': 'test_resource',
            'resource_data': {"test-key": "test-value"},
            'resource_id': None,
            'status': 'COMPLETE',
            'type': 'Foo'
        }
        actual = res.prepare_abandon()
        self.assertEqual(expected, actual)

    def test_state_set_invalid(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertRaises(ValueError, res.state_set, 'foo', 'bla')
        self.assertRaises(ValueError, res.state_set, 'foo', res.COMPLETE)
        self.assertRaises(ValueError, res.state_set, res.CREATE, 'bla')

    def test_state_del_stack(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        self.stack.action = self.stack.DELETE
        self.stack.status = self.stack.IN_PROGRESS
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.DELETE, res.action)
        self.assertEqual(res.COMPLETE, res.status)

    def test_type(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual('Foo', res.type())

    def test_has_interface_direct_match(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertTrue(res.has_interface('GenericResourceType'))

    def test_has_interface_no_match(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertFalse(res.has_interface('LookingForAnotherType'))

    def test_has_interface_mapping(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'OS::Test::GenericResource')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertTrue(res.has_interface('GenericResourceType'))

    def test_created_time(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_res_new', tmpl, self.stack)
        self.assertIsNone(res.created_time)
        res._store()
        self.assertIsNotNone(res.created_time)

    def test_updated_time(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res._store()
        stored_time = res.updated_time

        utmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        scheduler.TaskRunner(res.update, utmpl)()
        self.assertIsNotNone(res.updated_time)
        self.assertNotEqual(res.updated_time, stored_time)

    def test_update_replace(self):
        class TestResource(resource.Resource):
            properties_schema = {'a_string': {'Type': 'String'}}
            update_allowed_properties = ('a_string',)

        resource._register_class('TestResource', TestResource)

        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'TestResource')
        res = TestResource('test_resource', tmpl, self.stack)

        utmpl = rsrc_defn.ResourceDefinition('test_resource', 'TestResource',
                                             {'a_string': 'foo'})
        self.assertRaises(
            resource.UpdateReplace, scheduler.TaskRunner(res.update, utmpl))

    def test_updated_time_changes_only_on_update_calls(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res._store()
        self.assertIsNone(res.updated_time)

        res._store_or_update(res.UPDATE, res.COMPLETE, 'should not change')
        self.assertIsNone(res.updated_time)

    def test_store_or_update(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_res_upd', tmpl, self.stack)
        res._store_or_update(res.CREATE, res.IN_PROGRESS, 'test_store')
        self.assertIsNotNone(res.id)
        self.assertEqual(res.CREATE, res.action)
        self.assertEqual(res.IN_PROGRESS, res.status)
        self.assertEqual('test_store', res.status_reason)

        db_res = db_api.resource_get(res.context, res.id)
        self.assertEqual(res.CREATE, db_res.action)
        self.assertEqual(res.IN_PROGRESS, db_res.status)
        self.assertEqual('test_store', db_res.status_reason)

        res._store_or_update(res.CREATE, res.COMPLETE, 'test_update')
        self.assertEqual(res.CREATE, res.action)
        self.assertEqual(res.COMPLETE, res.status)
        self.assertEqual('test_update', res.status_reason)
        self.assertEqual(res.CREATE, db_res.action)
        self.assertEqual(res.COMPLETE, db_res.status)
        self.assertEqual('test_update', db_res.status_reason)

    def test_parsed_template(self):
        join_func = cfn_funcs.Join(None,
                                   'Fn::Join', [' ', ['bar', 'baz', 'quux']])
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            metadata={'foo': join_func})
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)

        parsed_tmpl = res.parsed_template()
        self.assertEqual('Foo', parsed_tmpl['Type'])
        self.assertEqual('bar baz quux', parsed_tmpl['Metadata']['foo'])

        self.assertEqual({'foo': 'bar baz quux'},
                         res.parsed_template('Metadata'))
        self.assertEqual({'foo': 'bar baz quux'},
                         res.parsed_template('Metadata', {'foo': 'bar'}))

    def test_parsed_template_default(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual({}, res.parsed_template('Metadata'))
        self.assertEqual({'foo': 'bar'},
                         res.parsed_template('Metadata', {'foo': 'bar'}))

    def test_metadata_default(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual({}, res.metadata_get())
        self.assertEqual({}, res.metadata)

    def test_equals_different_stacks(self):
        tmpl1 = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        tmpl2 = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        tmpl3 = rsrc_defn.ResourceDefinition('test_resource2', 'Bar')
        stack2 = parser.Stack(utils.dummy_context(), 'test_stack',
                              parser.Template(empty_template), stack_id=-1)
        res1 = generic_rsrc.GenericResource('test_resource', tmpl1, self.stack)
        res2 = generic_rsrc.GenericResource('test_resource', tmpl2, stack2)
        res3 = generic_rsrc.GenericResource('test_resource2', tmpl3, stack2)

        self.assertEqual(res1, res2)
        self.assertNotEqual(res1, res3)

    def test_equals_names(self):
        tmpl1 = rsrc_defn.ResourceDefinition('test_resource1', 'Foo')
        tmpl2 = rsrc_defn.ResourceDefinition('test_resource2', 'Foo')
        res1 = generic_rsrc.GenericResource('test_resource1',
                                            tmpl1, self.stack)
        res2 = generic_rsrc.GenericResource('test_resource2', tmpl2,
                                            self.stack)

        self.assertNotEqual(res1, res2)

    def test_update_template_diff_changed_modified(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            metadata={'foo': 123})
        update_snippet = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                                      metadata={'foo': 456})
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertEqual({'Metadata': {'foo': 456}}, diff)

    def test_update_template_diff_changed_add(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        update_snippet = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                                      metadata={'foo': 123})
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertEqual({'Metadata': {'foo': 123}}, diff)

    def test_update_template_diff_changed_remove(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            metadata={'foo': 123})
        update_snippet = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertEqual({'Metadata': None}, diff)

    def test_update_template_diff_properties_none(self):
        before_props = {}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        after_props = {}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({}, diff)

    def test_update_template_diff_properties_added(self):
        before_props = {}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        after_props = {'Foo': '123'}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': '123'}, diff)

    def test_update_template_diff_properties_removed_no_default_value(self):
        before_props = {'Foo': '123'}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            before_props)
        # Here should be used real property to get default value
        new_t = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        new_res = generic_rsrc.ResourceWithProps('new_res', new_t, self.stack)
        after_props = new_res.properties

        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': None}, diff)

    def test_update_template_diff_properties_removed_with_default_value(self):
        before_props = {'Foo': '123'}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            before_props)
        schema = {'Foo': {'Type': 'String', 'Default': '567'}}
        self.patchobject(generic_rsrc.ResourceWithProps, 'properties_schema',
                         new=schema)
        # Here should be used real property to get default value
        new_t = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        new_res = generic_rsrc.ResourceWithProps('new_res', new_t, self.stack)
        after_props = new_res.properties

        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': '567'}, diff)

    def test_update_template_diff_properties_changed(self):
        before_props = {'Foo': '123'}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            before_props)
        after_props = {'Foo': '456'}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': '456'}, diff)

    def test_update_template_diff_properties_notallowed(self):
        before_props = {'Foo': '123'}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            before_props)
        after_props = {'Bar': '456'}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Cat',)
        self.assertRaises(resource.UpdateReplace,
                          res.update_template_diff_properties,
                          after_props, before_props)

    def test_update_template_diff_properties_immutable_notsupported(self):
        before_props = {'Foo': 'bar', 'Parrot': 'dead',
                        'Spam': 'ham', 'Viking': 'axe'}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            before_props)
        schema = {'Foo': {'Type': 'String'},
                  'Viking': {'Type': 'String', 'Immutable': True},
                  'Spam': {'Type': 'String', 'Immutable': True},
                  'Parrot': {'Type': 'String', 'Immutable': True},
                  }
        after_props = {'Foo': 'baz', 'Parrot': 'dead',
                       'Spam': 'eggs', 'Viking': 'sword'}

        self.patchobject(generic_rsrc.ResourceWithProps,
                         'properties_schema', new=schema)
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl,
                                             self.stack)
        ex = self.assertRaises(exception.NotSupported,
                               res.update_template_diff_properties,
                               after_props, before_props)
        self.assertIn("Update to properties Spam, Viking of",
                      six.text_type(ex))

    def test_resource(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_create_fail_missing_req_prop(self):
        rname = 'test_resource'
        tmpl = rsrc_defn.ResourceDefinition(rname, 'Foo', {})
        res = generic_rsrc.ResourceWithRequiredProps(rname, tmpl, self.stack)

        estr = 'Property error : test_resource: Property Foo not assigned'
        create = scheduler.TaskRunner(res.create)
        err = self.assertRaises(exception.ResourceFailure, create)
        self.assertIn(estr, six.text_type(err))
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_fail_prop_typo(self):
        rname = 'test_resource'
        tmpl = rsrc_defn.ResourceDefinition(rname, 'GenericResourceType',
                                            {'Food': 'abc'})
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)

        estr = 'StackValidationFailed: Unknown Property Food'
        create = scheduler.TaskRunner(res.create)
        err = self.assertRaises(exception.ResourceFailure, create)
        self.assertIn(estr, six.text_type(err))
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_fail_metadata_parse_error(self):
        rname = 'test_resource'
        get_att = cfn_funcs.GetAtt(self.stack, 'Fn::GetAtt',
                                   ["ResourceA", "abc"])
        tmpl = rsrc_defn.ResourceDefinition(rname, 'GenericResourceType',
                                            properties={},
                                            metadata={'foo': get_att})
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)

        create = scheduler.TaskRunner(res.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_resource_after_destroy(self):
        rname = 'test_res_id_none'
        tmpl = rsrc_defn.ResourceDefinition(rname, 'GenericResourceType')
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)
        res.id = 'test_res_id'
        (res.action, res.status) = (res.INIT, res.DELETE)
        create = scheduler.TaskRunner(res.create)
        self.assertRaises(exception.ResourceFailure, create)
        scheduler.TaskRunner(res.destroy)()
        res.state_reset()
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_create_fail_retry(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        self.m.StubOutWithMock(timeutils, 'retry_backoff_delay')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')

        # first attempt to create fails
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(
            resource.ResourceInError(resource_name='test_resource',
                                     resource_status='ERROR',
                                     resource_type='GenericResourceType',
                                     resource_action='CREATE',
                                     status_reason='just because'))
        # delete error resource from first attempt
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)

        # second attempt to create succeeds
        timeutils.retry_backoff_delay(1, jitter_max=2.0).AndReturn(0.01)
        generic_rsrc.ResourceWithProps.handle_create().AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        self.m.VerifyAll()

    def test_create_fail_retry_disabled(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)

        self.m.StubOutWithMock(timeutils, 'retry_backoff_delay')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')

        # attempt to create fails
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(
            resource.ResourceInError(resource_name='test_resource',
                                     resource_status='ERROR',
                                     resource_type='GenericResourceType',
                                     resource_action='CREATE',
                                     status_reason='just because'))
        self.m.ReplayAll()

        estr = ('ResourceInError: Went to status ERROR due to "just because"')
        create = scheduler.TaskRunner(res.create)
        err = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(estr, six.text_type(err))
        self.assertEqual((res.CREATE, res.FAILED), res.state)

        self.m.VerifyAll()

    def test_create_deletes_fail_retry(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)

        self.m.StubOutWithMock(timeutils, 'retry_backoff_delay')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')

        # first attempt to create fails
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(
            resource.ResourceInError(resource_name='test_resource',
                                     resource_status='ERROR',
                                     resource_type='GenericResourceType',
                                     resource_action='CREATE',
                                     status_reason='just because'))
        # first attempt to delete fails
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(
            resource.ResourceInError(resource_name='test_resource',
                                     resource_status='ERROR',
                                     resource_type='GenericResourceType',
                                     resource_action='DELETE',
                                     status_reason='delete failed'))
        # second attempt to delete fails
        timeutils.retry_backoff_delay(1, jitter_max=2.0).AndReturn(0.01)
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(
            resource.ResourceInError(resource_name='test_resource',
                                     resource_status='ERROR',
                                     resource_type='GenericResourceType',
                                     resource_action='DELETE',
                                     status_reason='delete failed again'))

        # third attempt to delete succeeds
        timeutils.retry_backoff_delay(2, jitter_max=2.0).AndReturn(0.01)
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)

        # second attempt to create succeeds
        timeutils.retry_backoff_delay(1, jitter_max=2.0).AndReturn(0.01)
        generic_rsrc.ResourceWithProps.handle_create().AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        self.m.VerifyAll()

    def test_creates_fail_retry(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)

        self.m.StubOutWithMock(timeutils, 'retry_backoff_delay')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')

        # first attempt to create fails
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(
            resource.ResourceInError(resource_name='test_resource',
                                     resource_status='ERROR',
                                     resource_type='GenericResourceType',
                                     resource_action='CREATE',
                                     status_reason='just because'))
        # delete error resource from first attempt
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)

        # second attempt to create fails
        timeutils.retry_backoff_delay(1, jitter_max=2.0).AndReturn(0.01)
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(
            resource.ResourceInError(resource_name='test_resource',
                                     resource_status='ERROR',
                                     resource_type='GenericResourceType',
                                     resource_action='CREATE',
                                     status_reason='just because'))
        # delete error resource from second attempt
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)

        # third attempt to create succeeds
        timeutils.retry_backoff_delay(2, jitter_max=2.0).AndReturn(0.01)
        generic_rsrc.ResourceWithProps.handle_create().AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        self.m.VerifyAll()

    def test_preview(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        self.assertEqual(res, res.preview())

    def test_update_ok(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        generic_rsrc.ResourceWithProps.handle_update(
            utmpl, tmpl_diff, prop_diff).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(res.update, utmpl)()
        self.assertEqual((res.UPDATE, res.COMPLETE), res.state)

        self.assertEqual({'Foo': 'xyz'}, res._stored_properties_data)

        self.m.VerifyAll()

    def test_update_replace_with_resource_name(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        generic_rsrc.ResourceWithProps.handle_update(
            utmpl, tmpl_diff, prop_diff).AndRaise(resource.UpdateReplace(
                res.name))
        self.m.ReplayAll()
        # should be re-raised so parser.Stack can handle replacement
        updater = scheduler.TaskRunner(res.update, utmpl)
        ex = self.assertRaises(resource.UpdateReplace, updater)
        self.assertEqual('The Resource test_resource requires replacement.',
                         six.text_type(ex))
        self.m.VerifyAll()

    def test_update_replace_without_resource_name(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        generic_rsrc.ResourceWithProps.handle_update(
            utmpl, tmpl_diff, prop_diff).AndRaise(resource.UpdateReplace())
        self.m.ReplayAll()
        # should be re-raised so parser.Stack can handle replacement
        updater = scheduler.TaskRunner(res.update, utmpl)
        ex = self.assertRaises(resource.UpdateReplace, updater)
        self.assertEqual('The Resource Unknown requires replacement.',
                         six.text_type(ex))
        self.m.VerifyAll()

    def test_update_fail_missing_req_prop(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithRequiredProps('test_resource',
                                                     tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {})

        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_fail_prop_typo(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Food': 'xyz'})

        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_not_implemented(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        generic_rsrc.ResourceWithProps.handle_update(
            utmpl, tmpl_diff, prop_diff).AndRaise(NotImplemented)
        self.m.ReplayAll()
        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)
        self.m.VerifyAll()

    def test_check_supported(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'GenericResourceType')
        res = generic_rsrc.ResourceWithProps('test_res', tmpl, self.stack)
        res.handle_check = mock.Mock()
        scheduler.TaskRunner(res.check)()

        self.assertTrue(res.handle_check.called)
        self.assertEqual(res.CHECK, res.action)
        self.assertEqual(res.COMPLETE, res.status)
        self.assertNotIn('not supported', res.status_reason)

    def test_check_not_supported(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'GenericResourceType')
        res = generic_rsrc.ResourceWithProps('test_res', tmpl, self.stack)
        scheduler.TaskRunner(res.check)()

        self.assertIn('not supported', res.status_reason)
        self.assertEqual(res.CHECK, res.action)
        self.assertEqual(res.COMPLETE, res.status)

    def test_check_failed(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'GenericResourceType')
        res = generic_rsrc.ResourceWithProps('test_res', tmpl, self.stack)
        res.handle_check = mock.Mock()
        res.handle_check.side_effect = Exception('boom')

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertTrue(res.handle_check.called)
        self.assertEqual(res.CHECK, res.action)
        self.assertEqual(res.FAILED, res.status)
        self.assertIn('boom', res.status_reason)

    def test_suspend_resume_ok(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        scheduler.TaskRunner(res.suspend)()
        self.assertEqual((res.SUSPEND, res.COMPLETE), res.state)
        scheduler.TaskRunner(res.resume)()
        self.assertEqual((res.RESUME, res.COMPLETE), res.state)

    def test_suspend_fail_inprogress(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        res.state_set(res.CREATE, res.IN_PROGRESS)
        suspend = scheduler.TaskRunner(res.suspend)
        self.assertRaises(exception.ResourceFailure, suspend)

        res.state_set(res.UPDATE, res.IN_PROGRESS)
        suspend = scheduler.TaskRunner(res.suspend)
        self.assertRaises(exception.ResourceFailure, suspend)

        res.state_set(res.DELETE, res.IN_PROGRESS)
        suspend = scheduler.TaskRunner(res.suspend)
        self.assertRaises(exception.ResourceFailure, suspend)

    def test_resume_fail_not_suspend_complete(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        non_suspended_states = [s for s in
                                itertools.product(res.ACTIONS, res.STATUSES)
                                if s != (res.SUSPEND, res.COMPLETE)]
        for state in non_suspended_states:
            res.state_set(*state)
            resume = scheduler.TaskRunner(res.resume)
            self.assertRaises(exception.ResourceFailure, resume)

    def test_suspend_fail_exception(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps,
                               'handle_suspend')
        generic_rsrc.ResourceWithProps.handle_suspend().AndRaise(Exception())
        self.m.ReplayAll()

        suspend = scheduler.TaskRunner(res.suspend)
        self.assertRaises(exception.ResourceFailure, suspend)
        self.assertEqual((res.SUSPEND, res.FAILED), res.state)

    def test_resume_fail_exception(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_resume')
        generic_rsrc.ResourceWithProps.handle_resume().AndRaise(Exception())
        self.m.ReplayAll()

        res.state_set(res.SUSPEND, res.COMPLETE)

        resume = scheduler.TaskRunner(res.resume)
        self.assertRaises(exception.ResourceFailure, resume)
        self.assertEqual((res.RESUME, res.FAILED), res.state)

    def test_resource_class_to_template(self):

        class TestResource(resource.Resource):
            list_schema = {'wont_show_up': {'Type': 'Number'}}
            map_schema = {'will_show_up': {'Type': 'Integer'}}

            properties_schema = {
                'name': {'Type': 'String'},
                'bool': {'Type': 'Boolean'},
                'implemented': {'Type': 'String',
                                'Implemented': True,
                                'AllowedPattern': '.*',
                                'MaxLength': 7,
                                'MinLength': 2,
                                'Required': True},
                'not_implemented': {'Type': 'String',
                                    'Implemented': False},
                'number': {'Type': 'Number',
                           'MaxValue': 77,
                           'MinValue': 41,
                           'Default': 42},
                'list': {'Type': 'List', 'Schema': {'Type': 'Map',
                         'Schema': list_schema}},
                'map': {'Type': 'Map', 'Schema': map_schema},
            }

            attributes_schema = {
                'output1': attributes.Schema('output1_desc'),
                'output2': attributes.Schema('output2_desc')
            }

        expected_template = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'name': {'Type': 'String'},
                'bool': {'Type': 'Boolean',
                         'AllowedValues': ['True', 'true', 'False', 'false']},
                'implemented': {
                    'Type': 'String',
                    'AllowedPattern': '.*',
                    'MaxLength': 7,
                    'MinLength': 2
                },
                'number': {'Type': 'Number',
                           'MaxValue': 77,
                           'MinValue': 41,
                           'Default': 42},
                'list': {'Type': 'CommaDelimitedList'},
                'map': {'Type': 'Json'}
            },
            'Resources': {
                'TestResource': {
                    'Type': 'Test::Resource::resource',
                    'Properties': {
                        'name': {'Ref': 'name'},
                        'bool': {'Ref': 'bool'},
                        'implemented': {'Ref': 'implemented'},
                        'number': {'Ref': 'number'},
                        'list': {'Fn::Split': [",", {'Ref': 'list'}]},
                        'map': {'Ref': 'map'}
                    }
                }
            },
            'Outputs': {
                'output1': {
                    'Description': 'output1_desc',
                    'Value': '{"Fn::GetAtt": ["TestResource", "output1"]}'
                },
                'output2': {
                    'Description': 'output2_desc',
                    'Value': '{"Fn::GetAtt": ["TestResource", "output2"]}'
                }
            }
        }
        self.assertEqual(expected_template,
                         TestResource.resource_to_template(
                             'Test::Resource::resource'))

    def test_is_using_neutron(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        res = resource.Resource('aresource', snippet, self.stack)
        self.patch(
            'heat.engine.clients.os.neutron.NeutronClientPlugin._create')
        self.assertTrue(res.is_using_neutron())

    def test_is_not_using_neutron(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        res = resource.Resource('aresource', snippet, self.stack)
        mock_create = self.patch(
            'heat.engine.clients.os.neutron.NeutronClientPlugin._create')
        mock_create.side_effect = Exception()
        self.assertFalse(res.is_using_neutron())

    def _test_skip_validation_if_custom_constraint(self, tmpl):
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl, env=self.env)
        stack.store()
        path = ('heat.engine.clients.os.neutron.NetworkConstraint.'
                'validate_with_client')
        with mock.patch(path) as mock_validate:
            mock_validate.side_effect = neutron_exp.NeutronClientException
            rsrc2 = stack['bar']
            self.assertIsNone(rsrc2.validate())

    def test_ref_skip_validation_if_custom_constraint(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'OS::Test::GenericResource'},
                'bar': {
                    'Type': 'OS::Test::ResourceWithCustomConstraint',
                    'Properties': {
                        'Foo': {'Ref': 'foo'},
                    }
                }
            }
        })
        self._test_skip_validation_if_custom_constraint(tmpl)

    def test_hot_ref_skip_validation_if_custom_constraint(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithCustomConstraint',
                    'properties': {
                        'Foo': {'get_resource': 'foo'},
                    }
                }
            }
        })
        self._test_skip_validation_if_custom_constraint(tmpl)


class ResourceAdoptTest(HeatTestCase):
    def setUp(self):
        super(ResourceAdoptTest, self).setUp()
        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        self.patch('heat.engine.resource.warnings')

    def test_adopt_resource_success(self):
        adopt_data = '{}'
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  tmpl,
                                  stack_id=str(uuid.uuid4()),
                                  adopt_stack_data=json.loads(adopt_data))
        res = self.stack['foo']
        res_data = {
            "status": "COMPLETE",
            "name": "foo",
            "resource_data": {},
            "metadata": {},
            "resource_id": "test-res-id",
            "action": "CREATE",
            "type": "GenericResourceType"
        }
        adopt = scheduler.TaskRunner(res.adopt, res_data)
        adopt()
        self.assertEqual({}, res.metadata_get())
        self.assertEqual({}, res.metadata)
        self.assertEqual((res.ADOPT, res.COMPLETE), res.state)

    def test_adopt_with_resource_data_and_metadata(self):
        adopt_data = '{}'
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  tmpl,
                                  stack_id=str(uuid.uuid4()),
                                  adopt_stack_data=json.loads(adopt_data))
        res = self.stack['foo']
        res_data = {
            "status": "COMPLETE",
            "name": "foo",
            "resource_data": {"test-key": "test-value"},
            "metadata": {"os_distro": "test-distro"},
            "resource_id": "test-res-id",
            "action": "CREATE",
            "type": "GenericResourceType"
        }
        adopt = scheduler.TaskRunner(res.adopt, res_data)
        adopt()
        self.assertEqual("test-value",
                         db_api.resource_data_get(res, "test-key"))
        self.assertEqual({"os_distro": "test-distro"}, res.metadata_get())
        self.assertEqual({"os_distro": "test-distro"}, res.metadata)
        self.assertEqual((res.ADOPT, res.COMPLETE), res.state)

    def test_adopt_resource_missing(self):
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
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  tmpl,
                                  stack_id=str(uuid.uuid4()),
                                  adopt_stack_data=json.loads(adopt_data))
        res = self.stack['foo']
        adopt = scheduler.TaskRunner(res.adopt, None)
        self.assertRaises(exception.ResourceFailure, adopt)
        expected = 'Exception: Resource ID was not provided.'
        self.assertEqual(expected, res.status_reason)


class ResourceDependenciesTest(HeatTestCase):
    def setUp(self):
        super(ResourceDependenciesTest, self).setUp()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithPropsType',
                                 generic_rsrc.ResourceWithProps)

        self.deps = dependencies.Dependencies()

    def test_no_deps(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['foo']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)

    def test_ref(self):
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
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_ref(self):
        '''Test that HOT get_resource creates dependencies.'''
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_resource': 'foo'},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_nested_dict(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Base64': {'Ref': 'foo'}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_ref_nested_dict(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Base64': {'get_resource': 'foo'}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_nested_deep(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'Ref': 'foo'},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_ref_nested_deep(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'foo': {'Fn::Join': [",", ["blarg",
                                                   {'get_resource': 'foo'},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_fail(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'baz'},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        self.assertRaises(exception.StackValidationFailed,
                          stack.validate)

    def test_hot_ref_fail(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_resource': 'baz'},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               stack.validate)
        self.assertIn('"baz" (in bar.Properties.Foo)', six.text_type(ex))

    def test_getatt(self):
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
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_getatt(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_attr': ['foo', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_nested_dict(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Base64': {'Fn::GetAtt': ['foo', 'bar']}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_getatt_nested_dict(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Base64': {'get_attr': ['foo', 'bar']}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_nested_deep(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'Fn::GetAtt': ['foo',
                                                                   'bar']},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_getatt_nested_deep(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'get_attr': ['foo',
                                                                 'bar']},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_fail(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::GetAtt': ['baz', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', six.text_type(ex))

    def test_hot_getatt_fail(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_attr': ['baz', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', six.text_type(ex))

    def test_getatt_fail_nested_deep(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'Fn::GetAtt': ['foo',
                                                                   'bar']},
                                                   "wibble",
                                                   {'Fn::GetAtt': ['baz',
                                                                   'bar']}]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo.Fn::Join[1][3])',
                      six.text_type(ex))

    def test_hot_getatt_fail_nested_deep(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'get_attr': ['foo',
                                                                 'bar']},
                                                   "wibble",
                                                   {'get_attr': ['baz',
                                                                 'bar']}]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo.Fn::Join[1][3])',
                      six.text_type(ex))

    def test_dependson(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'foo',
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_dependson_hot(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'GenericResourceType',
                    'depends_on': 'foo',
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_dependson_fail(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'wibble',
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"wibble" (in foo)', six.text_type(ex))


class MetadataTest(HeatTestCase):
    def setUp(self):
        super(MetadataTest, self).setUp()
        self.stack = parser.Stack(utils.dummy_context(),
                                  'test_stack',
                                  parser.Template(empty_template))
        self.stack.store()

        metadata = {'Test': 'Initial metadata'}
        tmpl = rsrc_defn.ResourceDefinition('metadata_resource', 'Foo',
                                            metadata=metadata)
        self.res = generic_rsrc.GenericResource('metadata_resource',
                                                tmpl, self.stack)

        scheduler.TaskRunner(self.res.create)()
        self.addCleanup(self.stack.delete)
        self.patch('heat.engine.resource.warnings')

    def test_read_initial(self):
        self.assertEqual({'Test': 'Initial metadata'}, self.res.metadata_get())
        self.assertEqual({'Test': 'Initial metadata'}, self.res.metadata)

    def test_write(self):
        test_data = {'Test': 'Newly-written data'}
        self.res.metadata_set(test_data)
        self.assertEqual(test_data, self.res.metadata_get())

    def test_assign_attribute(self):
        test_data = {'Test': 'Newly-written data'}
        self.res.metadata = test_data
        self.assertEqual(test_data, self.res.metadata_get())
        self.assertEqual(test_data, self.res.metadata)


class ReducePhysicalResourceNameTest(HeatTestCase):
    scenarios = [
        ('one', dict(
            limit=10,
            original='one',
            reduced='one')),
        ('limit_plus_one', dict(
            will_reduce=True,
            limit=10,
            original='onetwothree',
            reduced='on-wothree')),
        ('limit_exact', dict(
            limit=11,
            original='onetwothree',
            reduced='onetwothree')),
        ('limit_minus_one', dict(
            limit=12,
            original='onetwothree',
            reduced='onetwothree')),
        ('limit_four', dict(
            will_reduce=True,
            limit=4,
            original='onetwothree',
            reduced='on-e')),
        ('limit_three', dict(
            will_raise=ValueError,
            limit=3,
            original='onetwothree')),
        ('three_nested_stacks', dict(
            will_reduce=True,
            limit=63,
            original=('ElasticSearch-MasterCluster-ccicxsm25ug6-MasterSvr1'
                      '-men65r4t53hh-MasterServer-gxpc3wqxy4el'),
            reduced=('El-icxsm25ug6-MasterSvr1-men65r4t53hh-'
                     'MasterServer-gxpc3wqxy4el'))),
        ('big_names', dict(
            will_reduce=True,
            limit=63,
            original=('MyReallyQuiteVeryLongStackName-'
                      'MyExtraordinarilyLongResourceName-ccicxsm25ug6'),
            reduced=('My-LongStackName-'
                     'MyExtraordinarilyLongResourceName-ccicxsm25ug6'))),
    ]

    will_raise = None

    will_reduce = False

    def test_reduce(self):
        if self.will_raise:
            self.assertRaises(
                self.will_raise,
                resource.Resource.reduce_physical_resource_name,
                self.original,
                self.limit)
        else:
            reduced = resource.Resource.reduce_physical_resource_name(
                self.original, self.limit)
            self.assertEqual(self.reduced, reduced)
            if self.will_reduce:
                # check it has been truncated to exactly the limit
                self.assertEqual(self.limit, len(reduced))
            else:
                # check that nothing has changed
                self.assertEqual(self.original, reduced)
