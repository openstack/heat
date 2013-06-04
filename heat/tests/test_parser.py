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
import uuid

from heat.common import context
from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import parser
from heat.engine import parameters
from heat.engine import template

from heat.tests.utils import stack_delete_after
from heat.tests import generic_resource as generic_rsrc

import heat.db as db_api


def join(raw):
    return parser.Template.resolve_joins(raw)


@attr(tag=['unit', 'parser'])
@attr(speed='fast')
class ParserTest(unittest.TestCase):

    def test_list(self):
        raw = ['foo', 'bar', 'baz']
        parsed = join(raw)
        for i in xrange(len(raw)):
            self.assertEqual(parsed[i], raw[i])
        self.assertTrue(parsed is not raw)

    def test_dict(self):
        raw = {'foo': 'bar', 'blarg': 'wibble'}
        parsed = join(raw)
        for k in raw:
            self.assertEqual(parsed[k], raw[k])
        self.assertTrue(parsed is not raw)

    def test_dict_list(self):
        raw = {'foo': ['bar', 'baz'], 'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual(parsed['blarg'], raw['blarg'])
        for i in xrange(len(raw['foo'])):
            self.assertEqual(parsed['foo'][i], raw['foo'][i])
        self.assertTrue(parsed is not raw)
        self.assertTrue(parsed['foo'] is not raw['foo'])

    def test_list_dict(self):
        raw = [{'foo': 'bar', 'blarg': 'wibble'}, 'baz', 'quux']
        parsed = join(raw)
        for i in xrange(1, len(raw)):
            self.assertEqual(parsed[i], raw[i])
        for k in raw[0]:
            self.assertEqual(parsed[0][k], raw[0][k])
        self.assertTrue(parsed is not raw)
        self.assertTrue(parsed[0] is not raw[0])

    def test_join(self):
        raw = {'Fn::Join': [' ', ['foo', 'bar', 'baz']]}
        self.assertEqual(join(raw), 'foo bar baz')

    def test_join_none(self):
        raw = {'Fn::Join': [' ', ['foo', None, 'baz']]}
        self.assertEqual(join(raw), 'foo  baz')

    def test_join_list(self):
        raw = [{'Fn::Join': [' ', ['foo', 'bar', 'baz']]}, 'blarg', 'wibble']
        parsed = join(raw)
        self.assertEqual(parsed[0], 'foo bar baz')
        for i in xrange(1, len(raw)):
            self.assertEqual(parsed[i], raw[i])
        self.assertTrue(parsed is not raw)

    def test_join_dict_val(self):
        raw = {'quux': {'Fn::Join': [' ', ['foo', 'bar', 'baz']]},
               'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual(parsed['quux'], 'foo bar baz')
        self.assertEqual(parsed['blarg'], raw['blarg'])
        self.assertTrue(parsed is not raw)

    def test_join_recursive(self):
        raw = {'Fn::Join': ['\n', [{'Fn::Join':
                                   [' ', ['foo', 'bar']]}, 'baz']]}
        self.assertEqual(join(raw), 'foo bar\nbaz')


mapping_template = template_format.parse('''{
  "Mappings" : {
    "ValidMapping" : {
      "TestKey" : { "TestValue" : "wibble" }
    },
    "InvalidMapping" : {
      "ValueList" : [ "foo", "bar" ],
      "ValueString" : "baz"
    },
    "MapList": [ "foo", { "bar" : "baz" } ],
    "MapString": "foobar"
  }
}''')


@attr(tag=['unit', 'parser', 'template'])
@attr(speed='fast')
class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()

    def tearDown(self):
        self.m.UnsetStubs()

    def test_defaults(self):
        empty = parser.Template({})
        try:
            empty[template.VERSION]
        except KeyError:
            pass
        else:
            self.fail('Expected KeyError for version not present')
        self.assertEqual(empty[template.DESCRIPTION], 'No description')
        self.assertEqual(empty[template.MAPPINGS], {})
        self.assertEqual(empty[template.PARAMETERS], {})
        self.assertEqual(empty[template.RESOURCES], {})
        self.assertEqual(empty[template.OUTPUTS], {})

    def test_invalid_section(self):
        tmpl = parser.Template({'Foo': ['Bar']})
        try:
            tmpl['Foo']
        except KeyError:
            pass
        else:
            self.fail('Expected KeyError for invalid template key')

    def test_find_in_map(self):
        tmpl = parser.Template(mapping_template)
        find = {'Fn::FindInMap': ["ValidMapping", "TestKey", "TestValue"]}
        self.assertEqual(tmpl.resolve_find_in_map(find), "wibble")

    def test_find_in_invalid_map(self):
        tmpl = parser.Template(mapping_template)
        finds = ({'Fn::FindInMap': ["InvalidMapping", "ValueList", "foo"]},
                 {'Fn::FindInMap': ["InvalidMapping", "ValueString", "baz"]},
                 {'Fn::FindInMap': ["MapList", "foo", "bar"]},
                 {'Fn::FindInMap': ["MapString", "foo", "bar"]})

        for find in finds:
            self.assertRaises(KeyError, tmpl.resolve_find_in_map, find)

    def test_bad_find_in_map(self):
        tmpl = parser.Template(mapping_template)
        finds = ({'Fn::FindInMap': "String"},
                 {'Fn::FindInMap': {"Dict": "String"}},
                 {'Fn::FindInMap': ["ShortList", "foo"]},
                 {'Fn::FindInMap': ["ReallyShortList"]})

        for find in finds:
            self.assertRaises(KeyError, tmpl.resolve_find_in_map, find)

    def test_param_refs(self):
        params = {'foo': 'bar', 'blarg': 'wibble'}
        p_snippet = {"Ref": "foo"}
        self.assertEqual(parser.Template.resolve_param_refs(p_snippet, params),
                         "bar")

    def test_param_refs_resource(self):
        params = {'foo': 'bar', 'blarg': 'wibble'}
        r_snippet = {"Ref": "baz"}
        self.assertEqual(parser.Template.resolve_param_refs(r_snippet, params),
                         r_snippet)

    def test_param_ref_missing(self):
        tmpl = {'Parameters': {'foo': {'Type': 'String', 'Required': True}}}
        params = parameters.Parameters('test', tmpl)
        snippet = {"Ref": "foo"}
        self.assertRaises(exception.UserParameterMissing,
                          parser.Template.resolve_param_refs,
                          snippet, params)

    def test_resource_refs(self):
        resources = {'foo': self.m.CreateMock(resource.Resource),
                     'blarg': self.m.CreateMock(resource.Resource)}
        resources['foo'].FnGetRefId().AndReturn('bar')
        self.m.ReplayAll()

        r_snippet = {"Ref": "foo"}
        self.assertEqual(parser.Template.resolve_resource_refs(r_snippet,
                                                               resources),
                         "bar")
        self.m.VerifyAll()

    def test_resource_refs_param(self):
        resources = {'foo': 'bar', 'blarg': 'wibble'}
        p_snippet = {"Ref": "baz"}
        self.assertEqual(parser.Template.resolve_resource_refs(p_snippet,
                                                               resources),
                         p_snippet)

    def test_join_reduce(self):
        join = {"Fn::Join": [" ", ["foo", "bar", "baz", {'Ref': 'baz'},
                "bink", "bonk"]]}
        self.assertEqual(
            parser.Template.reduce_joins(join),
            {"Fn::Join": [" ", ["foo bar baz", {'Ref': 'baz'}, "bink bonk"]]})

        join = {"Fn::Join": [" ", ["foo", {'Ref': 'baz'},
                                   "bink"]]}
        self.assertEqual(
            parser.Template.reduce_joins(join),
            {"Fn::Join": [" ", ["foo", {'Ref': 'baz'}, "bink"]]})

        join = {"Fn::Join": [" ", [{'Ref': 'baz'}]]}
        self.assertEqual(
            parser.Template.reduce_joins(join),
            {"Fn::Join": [" ", [{'Ref': 'baz'}]]})

    def test_join(self):
        join = {"Fn::Join": [" ", ["foo", "bar"]]}
        self.assertEqual(parser.Template.resolve_joins(join), "foo bar")

    def test_join_string(self):
        join = {"Fn::Join": [" ", "foo"]}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join)

    def test_join_dict(self):
        join = {"Fn::Join": [" ", {"foo": "bar"}]}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join)

    def test_join_wrong_num_args(self):
        join0 = {"Fn::Join": []}
        self.assertRaises(ValueError, parser.Template.resolve_joins,
                          join0)
        join1 = {"Fn::Join": [" "]}
        self.assertRaises(ValueError, parser.Template.resolve_joins,
                          join1)
        join3 = {"Fn::Join": [" ", {"foo": "bar"}, ""]}
        self.assertRaises(ValueError, parser.Template.resolve_joins,
                          join3)

    def test_join_string_nodelim(self):
        join1 = {"Fn::Join": "o"}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join1)
        join2 = {"Fn::Join": "oh"}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join2)
        join3 = {"Fn::Join": "ohh"}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join3)

    def test_join_dict_nodelim(self):
        join1 = {"Fn::Join": {"foo": "bar"}}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join1)
        join2 = {"Fn::Join": {"foo": "bar", "blarg": "wibble"}}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join2)
        join3 = {"Fn::Join": {"foo": "bar", "blarg": "wibble", "baz": "quux"}}
        self.assertRaises(TypeError, parser.Template.resolve_joins,
                          join3)

    def test_base64(self):
        snippet = {"Fn::Base64": "foobar"}
        # For now, the Base64 function just returns the original text, and
        # does not convert to base64 (see issue #133)
        self.assertEqual(parser.Template.resolve_base64(snippet), "foobar")

    def test_base64_list(self):
        list_snippet = {"Fn::Base64": ["foobar"]}
        self.assertRaises(TypeError, parser.Template.resolve_base64,
                          list_snippet)

    def test_base64_dict(self):
        dict_snippet = {"Fn::Base64": {"foo": "bar"}}
        self.assertRaises(TypeError, parser.Template.resolve_base64,
                          dict_snippet)


@attr(tag=['unit', 'parser', 'stack'])
@attr(speed='fast')
class StackTest(unittest.TestCase):
    def setUp(self):
        self.username = 'parser_stack_test_user'

        self.m = mox.Mox()

        self.ctx = context.get_admin_context()
        self.m.StubOutWithMock(self.ctx, 'username')
        self.ctx.username = self.username
        self.ctx.tenant_id = 'test_tenant'

        generic_rsrc.GenericResource.properties_schema = {}
        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)

        self.m.ReplayAll()

    def tearDown(self):
        self.m.UnsetStubs()

    def test_state_defaults(self):
        stack = parser.Stack(None, 'test_stack', parser.Template({}))
        self.assertEqual(stack.state, None)
        self.assertEqual(stack.state_description, '')

    def test_state(self):
        stack = parser.Stack(None, 'test_stack', parser.Template({}),
                             state='foo')
        self.assertEqual(stack.state, 'foo')
        stack.state_set('bar', '')
        self.assertEqual(stack.state, 'bar')

    def test_state_description(self):
        stack = parser.Stack(None, 'test_stack', parser.Template({}),
                             state_description='quux')
        self.assertEqual(stack.state_description, 'quux')
        stack.state_set('blarg', 'wibble')
        self.assertEqual(stack.state_description, 'wibble')

    def test_load_nonexistant_id(self):
        self.assertRaises(exception.NotFound, parser.Stack.load,
                          None, -1)

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the self.stack is properly cleaned up
    @stack_delete_after
    def test_identifier(self):
        self.stack = parser.Stack(self.ctx, 'identifier_test',
                                  parser.Template({}))
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(identifier.tenant, self.ctx.tenant_id)
        self.assertEqual(identifier.stack_name, 'identifier_test')
        self.assertTrue(identifier.stack_id)
        self.assertFalse(identifier.path)

    @stack_delete_after
    def test_set_param_id(self):
        dummy_stackid = 'STACKABCD1234'
        self.m.StubOutWithMock(uuid, 'uuid4')
        uuid.uuid4().AndReturn(dummy_stackid)
        self.m.ReplayAll()
        self.stack = parser.Stack(self.ctx, 'param_arn_test',
                                  parser.Template({}))
        exp_prefix = 'arn:openstack:heat::test_tenant:stacks/param_arn_test/'
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         exp_prefix + 'None')
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         exp_prefix + dummy_stackid)
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         identifier.arn())
        self.m.VerifyAll()

    @stack_delete_after
    def test_load_param_id(self):
        self.stack = parser.Stack(self.ctx, 'param_load_arn_test',
                                  parser.Template({}))
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         identifier.arn())

        newstack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(newstack.parameters['AWS::StackId'], identifier.arn())

    @stack_delete_after
    def test_created_time(self):
        self.stack = parser.Stack(self.ctx, 'creation_time_test',
                                  parser.Template({}))
        self.assertEqual(self.stack.created_time, None)
        self.stack.store()
        self.assertNotEqual(self.stack.created_time, None)

    @stack_delete_after
    def test_updated_time(self):
        self.stack = parser.Stack(self.ctx, 'update_time_test',
                                  parser.Template({}))
        self.assertEqual(self.stack.updated_time, None)
        self.stack.store()
        stored_time = self.stack.updated_time
        self.stack.state_set(self.stack.CREATE_IN_PROGRESS, 'testing')
        self.assertNotEqual(self.stack.updated_time, None)
        self.assertNotEqual(self.stack.updated_time, stored_time)

    @stack_delete_after
    def test_delete(self):
        self.stack = parser.Stack(self.ctx, 'delete_test',
                                  parser.Template({}))
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertEqual(db_s, None)
        self.assertEqual(self.stack.state, self.stack.DELETE_COMPLETE)

    @stack_delete_after
    def test_delete_rollback(self):
        self.stack = parser.Stack(self.ctx, 'delete_rollback_test',
                                  parser.Template({}), disable_rollback=False)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.stack.delete(action=self.stack.ROLLBACK)

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertEqual(db_s, None)
        self.assertEqual(self.stack.state, self.stack.ROLLBACK_COMPLETE)

    @stack_delete_after
    def test_delete_badaction(self):
        self.stack = parser.Stack(self.ctx, 'delete_badaction_test',
                                  parser.Template({}))
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.stack.delete(action="wibble")

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)
        self.assertEqual(self.stack.state, self.stack.DELETE_FAILED)

    @stack_delete_after
    def test_update_badstate(self):
        self.stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}),
                                  state=parser.Stack.CREATE_FAILED)
        stack_id = self.stack.store()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_FAILED)
        self.stack.update({})
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_FAILED)

    @stack_delete_after
    def test_resource_by_refid(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'resource_by_refid_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)
        self.assertTrue('AResource' in self.stack)
        resource = self.stack['AResource']
        resource.resource_id_set('aaaa')
        self.assertNotEqual(None, resource)
        self.assertEqual(resource, self.stack.resource_by_refid('aaaa'))

        resource.state = resource.DELETE_IN_PROGRESS
        self.assertEqual(None, self.stack.resource_by_refid('aaaa'))

        self.assertEqual(None, self.stack.resource_by_refid('bbbb'))

    @stack_delete_after
    def test_update_add(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_COMPLETE)
        self.assertTrue('BResource' in self.stack)

    @stack_delete_after
    def test_update_remove(self):
        tmpl = {'Resources': {
                'AResource': {'Type': 'GenericResourceType'},
                'BResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_COMPLETE)
        self.assertFalse('BResource' in self.stack)

    @stack_delete_after
    def test_update_description(self):
        tmpl = {'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Description': 'BTemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_COMPLETE)
        self.assertEqual(self.stack.t[template.DESCRIPTION], 'BTemplate')

    @stack_delete_after
    def test_update_modify_ok_replace(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        # patch in a dummy handle_update
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'xyz')
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_modify_update_failed(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_update
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_FAILED)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_FAILED)
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_modify_replace_failed_delete(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_update
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        # make the update fail deleting the existing resource
        self.m.StubOutWithMock(resource.Resource, 'destroy')
        resource.Resource.destroy().AndReturn("Error")
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_FAILED)
        self.m.VerifyAll()
        # Unset here so destroy() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    @stack_delete_after
    def test_update_modify_replace_failed_create(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_update
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        # patch in a dummy handle_create making the replace fail creating
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_FAILED)
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_add_failed_create(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making BResource fail creating
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_FAILED)
        self.assertTrue('BResource' in self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertTrue('BResource' in re_stack)
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_rollback(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # There will be two calls to handle_update, one for the new template
        # then another (with the initial template) for rollback
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)
        generic_rsrc.GenericResource.handle_update(
            tmpl['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement resource, but succeed the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        generic_rsrc.GenericResource.handle_create().AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.ROLLBACK_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_rollback_fail(self):
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema

        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # There will be two calls to handle_update, one for the new template
        # then another (with the initial template) for rollback
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)
        generic_rsrc.GenericResource.handle_update(
            tmpl['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement resource, and again on the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.ROLLBACK_FAILED)
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_rollback_add(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement resource, and succeed on the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.ROLLBACK_COMPLETE)
        self.assertFalse('BResource' in self.stack)
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_rollback_remove(self):
        tmpl = {'Resources': {
                'AResource': {'Type': 'GenericResourceType'},
                'BResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy destroy making the delete fail
        self.m.StubOutWithMock(resource.Resource, 'destroy')
        resource.Resource.destroy().AndReturn('Error')
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.ROLLBACK_COMPLETE)
        self.assertTrue('BResource' in self.stack)
        self.m.VerifyAll()
        # Unset here so destroy() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    @stack_delete_after
    def test_update_replace_by_reference(self):
        '''
        assertion:
        changes in dynamic attributes, due to other resources been updated
        are not ignored and can cause dependant resources to be updated.
        '''
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema
        tmpl = {'Resources': {
                'AResource': {'Type': 'GenericResourceType',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'GenericResourceType',
                              'Properties': {
                              'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'GenericResourceType',
                               'Properties': {
                               'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.assertEqual(self.stack['BResource'].properties['Foo'],
                         'AResource')

        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        br2_snip = {'Type': 'GenericResourceType',
                    'Properties': {'Foo': 'inst-007'}}
        generic_rsrc.GenericResource.handle_update(
            br2_snip).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'FnGetRefId')
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'AResource')
        generic_rsrc.GenericResource.FnGetRefId().MultipleTimes().AndReturn(
            'inst-007')
        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.UPDATE_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'smelly')
        self.assertEqual(self.stack['BResource'].properties['Foo'], 'inst-007')
        self.m.VerifyAll()

    @stack_delete_after
    def test_update_by_reference_and_rollback_1(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the first instance
        '''
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema
        tmpl = {'Resources': {
                'AResource': {'Type': 'GenericResourceType',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'GenericResourceType',
                              'Properties': {
                              'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'GenericResourceType',
                               'Properties': {
                               'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.assertEqual(self.stack['BResource'].properties['Foo'],
                         'AResource')

        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'FnGetRefId')
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')

        # mocks for first (failed update)
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'AResource')

        # mock to make the replace fail when creating the replacement resource
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)

        # mocks for second rollback update
        generic_rsrc.GenericResource.handle_update(
            tmpl['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        generic_rsrc.GenericResource.handle_create().AndReturn(None)
        generic_rsrc.GenericResource.FnGetRefId().MultipleTimes().AndReturn(
            'AResource')

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.ROLLBACK_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')

        self.m.VerifyAll()

    @stack_delete_after
    def test_update_by_reference_and_rollback_2(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the second instance
        '''
        # patch in a dummy property schema for GenericResource
        dummy_schema = {'Foo': {'Type': 'String'}}
        generic_rsrc.GenericResource.properties_schema = dummy_schema
        tmpl = {'Resources': {
                'AResource': {'Type': 'GenericResourceType',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'GenericResourceType',
                              'Properties': {
                              'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'GenericResourceType',
                               'Properties': {
                               'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.assertEqual(self.stack['BResource'].properties['Foo'],
                         'AResource')

        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_update')
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'FnGetRefId')
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')

        # mocks for first and second (failed update)
        generic_rsrc.GenericResource.handle_update(
            tmpl2['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)
        br2_snip = {'Type': 'GenericResourceType',
                    'Properties': {'Foo': 'inst-007'}}
        generic_rsrc.GenericResource.handle_update(
            br2_snip).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'AResource')
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')
        # self.state_set(self.UPDATE_IN_PROGRESS)
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')
        # self.state_set(self.DELETE_IN_PROGRESS)
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')
        # self.state_set(self.DELETE_COMPLETE)
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')
        # self.properties.validate()
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')
        # self.state_set(self.CREATE_IN_PROGRESS)
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.GenericResource.handle_create().AndReturn(None)
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)

        # mocks for second rollback update
        generic_rsrc.GenericResource.handle_update(
            tmpl['Resources']['AResource']).AndReturn(
                resource.Resource.UPDATE_REPLACE)
        br2_snip = {'Type': 'GenericResourceType',
                    'Properties': {'Foo': 'AResource'}}
        generic_rsrc.GenericResource.handle_update(
            br2_snip).AndReturn(
                resource.Resource.UPDATE_REPLACE)

        # self.state_set(self.DELETE_IN_PROGRESS)
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')
        # self.state_set(self.DELETE_IN_PROGRESS)
        generic_rsrc.GenericResource.FnGetRefId().AndReturn(
            'inst-007')

        generic_rsrc.GenericResource.handle_create().AndReturn(None)
        generic_rsrc.GenericResource.handle_create().AndReturn(None)

        # reverting to AResource
        generic_rsrc.GenericResource.FnGetRefId().MultipleTimes().AndReturn(
            'AResource')

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state, parser.Stack.ROLLBACK_COMPLETE)
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')

        self.m.VerifyAll()

    def test_stack_name_valid(self):
        stack = parser.Stack(None, 's', parser.Template({}))
        stack = parser.Stack(None, 'stack123', parser.Template({}))
        stack = parser.Stack(None, 'test.stack', parser.Template({}))
        stack = parser.Stack(None, 'test_stack', parser.Template({}))
        stack = parser.Stack(None, 'TEST', parser.Template({}))
        stack = parser.Stack(None, 'test-stack', parser.Template({}))

    def test_stack_name_invalid(self):
        self.assertRaises(ValueError, parser.Stack, None, '_foo',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, '1bad',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, '.kcats',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, 'test stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, ' teststack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, '^-^',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, '\"stack\"',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, '1234',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, 'cat|dog',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, '$(foo)',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, 'test/stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, 'test\stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, 'test::stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, 'test;stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, 'test~stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, None, '#test',
                          parser.Template({}))

    @stack_delete_after
    def test_resource_state_get_att(self):
        tmpl = {
            'Resources': {'AResource': {'Type': 'GenericResourceType'}},
            'Outputs': {'TestOutput': {'Value': {
                'Fn::GetAtt': ['AResource', 'Foo']}}
            }
        }

        self.stack = parser.Stack(self.ctx, 'resource_state_get_att',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state, parser.Stack.CREATE_COMPLETE)
        self.assertTrue('AResource' in self.stack)
        rsrc = self.stack['AResource']
        rsrc.resource_id_set('aaaa')
        self.assertEqual('AResource', rsrc.FnGetAtt('foo'))

        for state in (
                rsrc.CREATE_IN_PROGRESS,
                rsrc.CREATE_COMPLETE,
                rsrc.UPDATE_IN_PROGRESS,
                rsrc.UPDATE_COMPLETE):
            rsrc.state = state
            self.assertEqual('AResource', self.stack.output('TestOutput'))
        for state in (
                rsrc.CREATE_FAILED,
                rsrc.DELETE_IN_PROGRESS,
                rsrc.DELETE_FAILED,
                rsrc.DELETE_COMPLETE,
                rsrc.UPDATE_FAILED,
                None):
            rsrc.state = state
            self.assertEqual(None, self.stack.output('TestOutput'))

        rsrc.state = rsrc.CREATE_COMPLETE
