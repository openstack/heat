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


import nose
import unittest
from nose.plugins.attrib import attr
import mox
import json

from heat.common import context
from heat.common import exception
from heat.engine import format
from heat.engine import parser
from heat.engine import parameters
from heat.engine import template
from heat.engine.resources import Resource


def join(raw):
    def handle_join(args):
        delim, strs = args
        return delim.join(strs)

    return template._resolve(lambda k, v: k == 'Fn::Join', handle_join, raw)


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
        raw = {'Fn::Join': ['\n', [{'Fn::Join': [' ', ['foo', 'bar']]},
                                  'baz']]}
        self.assertEqual(join(raw), 'foo bar\nbaz')


mapping_template = format.parse_to_template('''{
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
        resources = {'foo': self.m.CreateMock(Resource),
                     'blarg': self.m.CreateMock(Resource)}
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

    def test_identifier(self):
        stack = parser.Stack(self.ctx, 'identifier_test',
                             parser.Template({}))
        stack.store()
        identifier = stack.identifier()
        self.assertEqual(identifier.tenant, self.ctx.tenant)
        self.assertEqual(identifier.stack_name, 'identifier_test')
        self.assertTrue(identifier.stack_id)
        self.assertFalse(identifier.path)

    def test_created_time(self):
        stack = parser.Stack(self.ctx, 'creation_time_test',
                             parser.Template({}))
        self.assertEqual(stack.created_time, None)
        stack.store()
        self.assertNotEqual(stack.created_time, None)

    def test_updated_time(self):
        stack = parser.Stack(self.ctx, 'update_time_test',
                             parser.Template({}))
        self.assertEqual(stack.updated_time, None)
        stack.store()
        stored_time = stack.updated_time
        stack.state_set(stack.CREATE_IN_PROGRESS, 'testing')
        self.assertNotEqual(stack.updated_time, None)
        self.assertNotEqual(stack.updated_time, stored_time)

# allows testing of the test directly, shown below
if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
