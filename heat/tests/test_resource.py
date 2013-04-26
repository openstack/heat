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


import unittest
from nose.plugins.attrib import attr
import mox

from heat.common import context
from heat.common import exception
from heat.engine import parser
from heat.engine import resource
from heat.openstack.common import uuidutils

from heat.tests import generic_resource as generic_rsrc


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class ResourceTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.stack = parser.Stack(None, 'test_stack', parser.Template({}),
                                  stack_id=uuidutils.generate_uuid())

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)

    def tearDown(self):
        self.m.UnsetStubs()

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
        self.assertEqual(res.state, None)
        self.assertEqual(res.state_description, '')

    def test_state(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.state_set('bar')
        self.assertEqual(res.state, 'bar')

    def test_state_description(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.state_set('blarg', 'wibble')
        self.assertEqual(res.state_description, 'wibble')

    def test_type(self):
        tmpl = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.type(), 'Foo')

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
        res.state_set(res.CREATE_IN_PROGRESS, 'testing')
        self.assertNotEqual(res.updated_time, None)
        self.assertNotEqual(res.updated_time, stored_time)

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
        stack2 = parser.Stack(None, 'test_stack', parser.Template({}),
                              stack_id=-1)
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
        self.assertRaises(NotImplementedError, res.update_template_diff,
                          update_snippet)

    def test_update_template_diff_changed_notallowed(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Bar'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertRaises(NotImplementedError, res.update_template_diff,
                          update_snippet)

    def test_update_template_diff_changed_modified(self):
        tmpl = {'Type': 'Foo', 'Metadata': {'foo': 123}}
        update_snippet = {'Type': 'Foo', 'Metadata': {'foo': 456}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Metadata',)
        diff = res.update_template_diff(json_snippet=update_snippet)
        self.assertEqual(diff, {'Metadata': {'foo': 456}})

    def test_update_template_diff_changed_add(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Foo', 'Metadata': {'foo': 123}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Metadata',)
        diff = res.update_template_diff(json_snippet=update_snippet)
        self.assertEqual(diff, {'Metadata': {'foo': 123}})

    def test_update_template_diff_changed_remove(self):
        tmpl = {'Type': 'Foo', 'Metadata': {'foo': 123}}
        update_snippet = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_keys = ('Metadata',)
        diff = res.update_template_diff(json_snippet=update_snippet)
        self.assertEqual(diff, {'Metadata': None})

    def test_update_template_diff_properties_none(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Foo'}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff_properties(json_snippet=update_snippet)
        self.assertEqual(diff, {})

    def test_update_template_diff_properties_added(self):
        tmpl = {'Type': 'Foo'}
        update_snippet = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Bar',)
        diff = res.update_template_diff_properties(json_snippet=update_snippet)
        self.assertEqual(diff, {'Bar': 123})

    def test_update_template_diff_properties_removed(self):
        tmpl = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        update_snippet = {'Type': 'Foo', 'Properties': {}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Bar',)
        diff = res.update_template_diff_properties(json_snippet=update_snippet)
        self.assertEqual(diff, {'Bar': None})

    def test_update_template_diff_properties_changed(self):
        tmpl = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        update_snippet = {'Type': 'Foo', 'Properties': {'Bar': 456}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Bar',)
        diff = res.update_template_diff_properties(json_snippet=update_snippet)
        self.assertEqual(diff, {'Bar': 456})

    def test_update_template_diff_properties_notallowed(self):
        tmpl = {'Type': 'Foo', 'Properties': {'Bar': 123}}
        update_snippet = {'Type': 'Foo', 'Properties': {'Bar': 456}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Cat',)
        self.assertRaises(NotImplementedError,
                          res.update_template_diff_properties,
                          update_snippet)

    def test_resource(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(None, res.create())
        self.assertEqual(res.CREATE_COMPLETE, res.state)

    def test_create_fail_missing_req_prop(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String', 'Required': True}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Type': 'GenericResourceType', 'Properties': {}}
        rname = 'test_resource'
        res = generic_rsrc.GenericResource(rname, tmpl, self.stack)

        estr = 'Property error : test_resource: Property Foo not assigned'
        self.assertRaises(exception.ResourceFailure, res.create)
        self.assertEqual(res.CREATE_FAILED, res.state)

    def test_create_fail_prop_typo(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String', 'Required': True}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Food': 'abc'}}
        rname = 'test_resource'
        res = generic_rsrc.GenericResource(rname, tmpl, self.stack)

        estr = 'Property error : test_resource: Property Foo not assigned'
        self.assertRaises(exception.ResourceFailure, res.create)
        self.assertEqual(res.CREATE_FAILED, res.state)

    def test_update_ok(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(None, res.create())
        self.assertEqual(res.CREATE_COMPLETE, res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'xyz'}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(utmpl).AndReturn(
            resource.Resource.UPDATE_COMPLETE)
        self.m.ReplayAll()

        self.assertEqual(res.UPDATE_COMPLETE, res.update(utmpl))
        self.assertEqual(res.UPDATE_COMPLETE, res.state)
        self.m.VerifyAll()

    def test_update_fail_missing_req_prop(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String', 'Required': True}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(None, res.create())
        self.assertEqual(res.CREATE_COMPLETE, res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {}}

        estr = 'Property error : test_resource: Property Foo not assigned'
        self.assertEqual(estr, res.update(utmpl))
        self.assertEqual(res.UPDATE_FAILED, res.state)

    def test_update_fail_prop_typo(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Type': 'GenericResourceType', 'Properties': {'Foo': 'abc'}}
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(None, res.create())
        self.assertEqual(res.CREATE_COMPLETE, res.state)

        utmpl = {'Type': 'GenericResourceType', 'Properties': {'Food': 'xyz'}}

        self.assertEqual('Unknown Property Food', res.update(utmpl))
        self.assertEqual(res.UPDATE_FAILED, res.state)


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class MetadataTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        tmpl = {
            'Type': 'Foo',
            'Metadata': {'Test': 'Initial metadata'}
        }
        ctx = context.get_admin_context()
        self.m.StubOutWithMock(ctx, 'username')
        ctx.username = 'metadata_test_user'
        self.stack = parser.Stack(ctx, 'test_stack', parser.Template({}))
        self.stack.store()
        self.res = generic_rsrc.GenericResource('metadata_resource',
                                                tmpl, self.stack)
        self.res.create()

    def tearDown(self):
        self.stack.delete()
        self.m.UnsetStubs()

    def test_read_initial(self):
        self.assertEqual(self.res.metadata, {'Test': 'Initial metadata'})

    def test_write(self):
        test_data = {'Test': 'Newly-written data'}
        self.res.metadata = test_data
        self.assertEqual(self.res.metadata, test_data)
