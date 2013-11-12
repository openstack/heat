# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import testscenarios

from heat.common import exception
from heat.engine import dependencies
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import template
from heat.engine import environment
from heat.openstack.common import uuidutils
import heat.db.api as db_api

from heat.tests import generic_resource as generic_rsrc
from heat.tests.common import HeatTestCase
from heat.tests import utils


load_tests = testscenarios.load_tests_apply_scenarios


class ResourceTest(HeatTestCase):
    def setUp(self):
        super(ResourceTest, self).setUp()
        utils.setup_dummy_db()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)

        env = environment.Environment()
        env.load({u'resource_registry':
                  {u'OS::Test::GenericResource': u'GenericResourceType'}})

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  parser.Template({}), env=env,
                                  stack_id=uuidutils.generate_uuid())

    def test_get_class_ok(self):
        cls = resource.get_class('GenericResourceType')
        self.assertEqual(cls, generic_rsrc.GenericResource)

    def test_get_class_noexist(self):
        self.assertRaises(exception.StackValidationFailed, resource.get_class,
                          'NoExistResourceType')

    def test_resource_new_ok(self):
        snippet = {'Type': 'GenericResourceType'}
        res = resource.Resource('aresource', snippet, self.stack)

    def test_resource_new_err(self):
        snippet = {'Type': 'NoExistResourceType'}
        self.assertRaises(exception.StackValidationFailed,
                          resource.Resource, 'aresource', snippet, self.stack)

    def test_state_defaults(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_res_def', tmpl, self.stack)
        self.assertEqual(res.state, (res.INIT, res.COMPLETE))
        self.assertEqual(res.status_reason, '')

    def test_state_set(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.state_set(res.CREATE, res.COMPLETE, 'wibble')
        self.assertEqual(res.action, res.CREATE)
        self.assertEqual(res.status, res.COMPLETE)
        self.assertEqual(res.state, (res.CREATE, res.COMPLETE))
        self.assertEqual(res.status_reason, 'wibble')

    def test_state_set_invalid(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertRaises(ValueError, res.state_set, 'foo', 'bla')
        self.assertRaises(ValueError, res.state_set, 'foo', res.COMPLETE)
        self.assertRaises(ValueError, res.state_set, res.CREATE, 'bla')

    def test_state_del_stack(self):
        tmpl = {'Type': 'Foo'}
        self.stack.action = self.stack.DELETE
        self.stack.status = self.stack.IN_PROGRESS
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.DELETE, res.action)
        self.assertEqual(res.COMPLETE, res.status)

    def test_type(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.type(), 'Foo')

    def test_has_interface_direct_match(self):
        tmpl = {'Type': 'GenericResourceType'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertTrue(res.has_interface('GenericResourceType'))

    def test_has_interface_no_match(self):
        tmpl = {'Type': 'GenericResourceType'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertFalse(res.has_interface('LookingForAnotherType'))

    def test_has_interface_mapping(self):
        tmpl = {'Type': 'OS::Test::GenericResource'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertTrue(res.has_interface('GenericResourceType'))

    def test_created_time(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_res_new', tmpl, self.stack)
        self.assertEqual(res.created_time, None)
        res._store()
        self.assertNotEqual(res.created_time, None)

    def test_updated_time(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_res_upd', tmpl, self.stack)
        res._store()
        stored_time = res.updated_time
        res.state_set(res.CREATE, res.IN_PROGRESS, 'testing')
        self.assertNotEqual(res.updated_time, None)
        self.assertNotEqual(res.updated_time, stored_time)

    def test_store_or_update(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_res_upd', tmpl, self.stack)
        res._store_or_update(res.CREATE, res.IN_PROGRESS, 'test_store')
        self.assertNotEqual(None, res.id)
        self.assertEqual(res.action, res.CREATE)
        self.assertEqual(res.status, res.IN_PROGRESS)
        self.assertEqual(res.status_reason, 'test_store')

        db_res = r = db_api.resource_get(None, res.id)
        self.assertEqual(db_res.action, res.CREATE)
        self.assertEqual(db_res.status, res.IN_PROGRESS)
        self.assertEqual(db_res.status_reason, 'test_store')

        res._store_or_update(res.CREATE, res.COMPLETE, 'test_update')
        self.assertEqual(res.action, res.CREATE)
        self.assertEqual(res.status, res.COMPLETE)
        self.assertEqual(res.status_reason, 'test_update')
        self.assertEqual(db_res.action, res.CREATE)
        self.assertEqual(db_res.status, res.COMPLETE)
        self.assertEqual(db_res.status_reason, 'test_update')

    def test_parsed_template(self):
        tmpl = {
            'Type': 'Foo',
            'foo': {'Fn::Join': [' ', ['bar', 'baz', 'quux']]}
        }
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)

        parsed_tmpl = res.parsed_template()
        self.assertEqual(parsed_tmpl['Type'], 'Foo')
        self.assertEqual(parsed_tmpl['foo'], 'bar baz quux')

        self.assertEqual(res.parsed_template('foo'), 'bar baz quux')
        self.assertEqual(res.parsed_template('foo', 'bar'), 'bar baz quux')

    def test_parsed_template_default(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.parsed_template('foo'), {})
        self.assertEqual(res.parsed_template('foo', 'bar'), 'bar')

    def test_metadata_default(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.metadata, {})

    def test_equals_different_stacks(self):
        tmpl1 = {'Type': 'Foo'}
        tmpl2 = {'Type': 'Foo'}
        tmpl3 = {'Type': 'Bar'}
        stack2 = parser.Stack(utils.dummy_context(), 'test_stack',
                              parser.Template({}), stack_id=-1)
        res1 = generic_rsrc.GenericResource('test_resource', tmpl1, self.stack)
        res2 = generic_rsrc.GenericResource('test_resource', tmpl2, stack2)
        res3 = generic_rsrc.GenericResource('test_resource2', tmpl3, stack2)

        self.assertEqual(res1, res2)
        self.assertNotEqual(res1, res3)

    def test_equals_names(self):
        tmpl1 = {'Type': 'Foo'}
        tmpl2 = {'Type': 'Foo'}
        res1 = generic_rsrc.GenericResource('test_resource1',
                                            tmpl1, self.stack)
        res2 = generic_rsrc.GenericResource('test_resource2', tmpl2,
                                            self.stack)

        self.assertNotEqual(res1, res2)

    def test_update_template_diff_empty(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertRaises(resource.UpdateReplace, res.update_template_diff,
                          update_snippet, tmpl)

    def test_update_template_diff_changed_notallowed(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Bar'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertRaises(resource.UpdateReplace, res.update_template_diff,
                          update_snippet, tmpl)

    def test_update_template_diff_changed_modified(self):
        tmpl = {'Type': 'Foo', 'Metadata': {'foo': 123}}
        update_snippet = {'Type': 'Foo', 'Metadata': {'foo': 456}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Metadata',)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertEqual(diff, {'Metadata': {'foo': 456}})

    def test_update_template_diff_changed_add(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Foo', 'Metadata': {'foo': 123}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Metadata',)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertEqual(diff, {'Metadata': {'foo': 123}})

    def test_update_template_diff_changed_remove(self):
        tmpl = {'Type': 'Foo', 'Metadata': {'foo': 123}}
        update_snippet = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Metadata',)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertEqual(diff, {'Metadata': None})

    def test_update_template_diff_properties_none(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff_properties(update_snippet, tmpl)
        self.assertEqual(diff, {})

    def test_update_template_diff_properties_added(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Bar',)
        diff = res.update_template_diff_properties(update_snippet, tmpl)
        self.assertEqual(diff, {'Bar': 123})

    def test_update_template_diff_properties_removed(self):
        tmpl = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        update_snippet = {'Type': 'Foo', 'Properties': {}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Bar',)
        diff = res.update_template_diff_properties(update_snippet, tmpl)
        self.assertEqual(diff, {'Bar': None})

    def test_update_template_diff_properties_changed(self):
        tmpl = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        update_snippet = {'Type': 'Foo', 'Properties': {'Bar': 456}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Bar',)
        diff = res.update_template_diff_properties(update_snippet, tmpl)
        self.assertEqual(diff, {'Bar': 456})

    def test_update_template_diff_properties_notallowed(self):
        tmpl = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        update_snippet = {'Type': 'Foo', 'Properties': {'Bar': 456}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Cat',)
        self.assertRaises(resource.UpdateReplace,
                          res.update_template_diff_properties,
                          update_snippet, tmpl)

    def test_resource(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_create_fail_missing_req_prop(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {}}
        rname = 'test_resource'
        res = generic_rsrc.ResourceWithRequiredProps(rname, tmpl, self.stack)

        estr = 'Property error : test_resource: Property Foo not assigned'
        create = scheduler.TaskRunner(res.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_fail_prop_typo(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Food': 'abc'}}
        rname = 'test_resource'
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)

        estr = 'Property error : test_resource: Property Foo not assigned'
        create = scheduler.TaskRunner(res.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_fail_metadata_parse_error(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {},
                'Metadata': {"Fn::GetAtt": ["ResourceA", "abc"]}}
        rname = 'test_resource'
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)

        create = scheduler.TaskRunner(res.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_resource_after_destroy(self):
        tmpl = {'Type': 'GenericResourceType'}
        rname = 'test_res_id_none'
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)
        res.id = 'test_res_id'
        (res.action, res.status) = (res.INIT, res.DELETE)
        self.assertRaises(exception.ResourceFailure, res.create)
        scheduler.TaskRunner(res.destroy)()
        res.state_reset()
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_update_ok(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Properties',)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'xyz'}}
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        generic_rsrc.ResourceWithProps.handle_update(
            utmpl, tmpl_diff, prop_diff).AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(res.update, utmpl)()
        self.assertEqual((res.UPDATE, res.COMPLETE), res.state)
        self.m.VerifyAll()

    def test_update_replace(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Properties',)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'xyz'}}
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        generic_rsrc.ResourceWithProps.handle_update(
            utmpl, tmpl_diff, prop_diff).AndRaise(resource.UpdateReplace())
        self.m.ReplayAll()
        # should be re-raised so parser.Stack can handle replacement
        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(resource.UpdateReplace, updater)
        self.m.VerifyAll()

    def test_update_fail_missing_req_prop(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.ResourceWithRequiredProps('test_resource',
                                                     tmpl, self.stack)
        res.update_allowed_keys = ('Properties',)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {}}

        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_fail_prop_typo(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Properties',)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {'Food': 'xyz'}}

        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_not_implemented(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Properties',)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'xyz'}}
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

    def test_suspend_resume_ok(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Properties',)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        scheduler.TaskRunner(res.suspend)()
        self.assertEqual((res.SUSPEND, res.COMPLETE), res.state)
        scheduler.TaskRunner(res.resume)()
        self.assertEqual((res.RESUME, res.COMPLETE), res.state)

    def test_suspend_fail_inprogress(self):
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
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
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
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
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
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
        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
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
                'map': {'Type': 'Map', 'Schema': {'Type': 'Map',
                        'Schema': map_schema}},
            }

            attributes_schema = {
                'output1': 'output1_desc',
                'output2': 'output2_desc'
            }

        expected_template = {
            'Parameters': {
                'name': {'Type': 'String'},
                'bool': {'Type': 'Boolean'},
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
                        'list': {'Fn::Split': {'Ref': 'list'}},
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
                         'Test::Resource::resource')
                         )


class ResourceDependenciesTest(HeatTestCase):
    def setUp(self):
        super(ResourceDependenciesTest, self).setUp()
        utils.setup_dummy_db()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithPropsType',
                                 generic_rsrc.ResourceWithProps)

        self.deps = dependencies.Dependencies()

    def test_no_deps(self):
        tmpl = template.Template({
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['foo']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)

    def test_ref(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)

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
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_nested_dict(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)

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
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_nested_deep(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)

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
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_fail(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', str(ex))

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
        stack = parser.Stack(None, 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', str(ex))

    def test_getatt(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)

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
                    'Properties': {
                        'Foo': {'get_attr': ['foo', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_nested_dict(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)

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
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_nested_deep(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)

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
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_fail(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', str(ex))

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
        stack = parser.Stack(None, 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', str(ex))

    def test_getatt_fail_nested_deep(self):
        tmpl = template.Template({
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
        stack = parser.Stack(None, 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo.Fn::Join[1][3])', str(ex))

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
        stack = parser.Stack(None, 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo.Fn::Join[1][3])', str(ex))

    def test_dependson(self):
        tmpl = template.Template({
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'foo',
                }
            }
        })
        stack = parser.Stack(None, 'test', tmpl)

        res = stack['bar']
        res.add_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_dependson_fail(self):
        tmpl = template.Template({
            'Resources': {
                'foo': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'wibble',
                }
            }
        })
        stack = parser.Stack(None, 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"wibble" (in foo)', str(ex))


class MetadataTest(HeatTestCase):
    def setUp(self):
        super(MetadataTest, self).setUp()
        tmpl = {
            'Type': 'Foo',
            'Metadata': {'Test': 'Initial metadata'}
        }
        utils.setup_dummy_db()
        self.stack = parser.Stack(utils.dummy_context(),
                                  'test_stack', parser.Template({}))
        self.stack.store()
        self.res = generic_rsrc.GenericResource('metadata_resource',
                                                tmpl, self.stack)
        scheduler.TaskRunner(self.res.create)()
        self.addCleanup(self.stack.delete)

    def test_read_initial(self):
        self.assertEqual(self.res.metadata, {'Test': 'Initial metadata'})

    def test_write(self):
        test_data = {'Test': 'Newly-written data'}
        self.res.metadata = test_data
        self.assertEqual(self.res.metadata, test_data)


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
                self.assertEqual(len(reduced), self.limit)
            else:
                # check that nothing has changed
                self.assertEqual(self.original, reduced)
