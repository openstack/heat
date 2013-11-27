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

import json
import time

from keystoneclient import exceptions as kc_exceptions

from oslo.config import cfg

from heat.engine import environment
from heat.common import exception
from heat.common import template_format
from heat.common import urlfetch
from heat.engine import clients
from heat.engine import resource
from heat.engine import parser
from heat.engine import parameters
from heat.engine import scheduler
from heat.engine import template

from heat.tests.fakes import FakeKeystoneClient
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes
from heat.tests import generic_resource as generic_rsrc

import heat.db.api as db_api


def join(raw):
    return parser.Template.resolve_joins(raw)


class ParserTest(HeatTestCase):

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


class TemplateTest(HeatTestCase):

    def setUp(self):
        super(TemplateTest, self).setUp()
        self.ctx = utils.dummy_context()

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

    def test_invalid_template(self):
        scanner_error = '''
1
Mappings:
  ValidMapping:
    TestKey: TestValue
'''
        parser_error = '''
Mappings:
  ValidMapping:
    TestKey: {TestKey1: "Value1" TestKey2: "Value2"}
'''

        self.assertRaises(ValueError, template_format.parse, scanner_error)
        self.assertRaises(ValueError, template_format.parse, parser_error)

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
        tmpl = parser.Template(tmpl)
        params = parameters.Parameters('test', tmpl, validate_value=False)
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

    def test_select_from_list(self):
        data = {"Fn::Select": ["1", ["foo", "bar"]]}
        self.assertEqual(parser.Template.resolve_select(data), "bar")

    def test_select_from_list_not_int(self):
        data = {"Fn::Select": ["one", ["foo", "bar"]]}
        self.assertRaises(TypeError, parser.Template.resolve_select,
                          data)

    def test_select_from_list_out_of_bound(self):
        data = {"Fn::Select": ["0", ["foo", "bar"]]}
        self.assertEqual(parser.Template.resolve_select(data), "foo")
        data = {"Fn::Select": ["1", ["foo", "bar"]]}
        self.assertEqual(parser.Template.resolve_select(data), "bar")
        data = {"Fn::Select": ["2", ["foo", "bar"]]}
        self.assertEqual(parser.Template.resolve_select(data), "")

    def test_select_from_dict(self):
        data = {"Fn::Select": ["red", {"red": "robin", "re": "foo"}]}
        self.assertEqual(parser.Template.resolve_select(data), "robin")

    def test_select_from_none(self):
        data = {"Fn::Select": ["red", None]}
        self.assertEqual(parser.Template.resolve_select(data), "")

    def test_select_from_dict_not_str(self):
        data = {"Fn::Select": ["1", {"red": "robin", "re": "foo"}]}
        self.assertRaises(TypeError, parser.Template.resolve_select,
                          data)

    def test_select_from_dict_not_existing(self):
        data = {"Fn::Select": ["green", {"red": "robin", "re": "foo"}]}
        self.assertEqual(parser.Template.resolve_select(data), "")

    def test_select_from_serialized_json_map(self):
        js = json.dumps({"red": "robin", "re": "foo"})
        data = {"Fn::Select": ["re", js]}
        self.assertEqual(parser.Template.resolve_select(data), "foo")

    def test_select_from_serialized_json_list(self):
        js = json.dumps(["foo", "fee", "fum"])
        data = {"Fn::Select": ["0", js]}
        self.assertEqual(parser.Template.resolve_select(data), "foo")

    def test_select_from_serialized_json_wrong(self):
        js = "this is really not serialized json"
        data = {"Fn::Select": ["not", js]}
        self.assertRaises(ValueError, parser.Template.resolve_select,
                          data)

    def test_select_wrong_num_args(self):
        join0 = {"Fn::Select": []}
        self.assertRaises(ValueError, parser.Template.resolve_select,
                          join0)
        join1 = {"Fn::Select": ["4"]}
        self.assertRaises(ValueError, parser.Template.resolve_select,
                          join1)
        join3 = {"Fn::Select": ["foo", {"foo": "bar"}, ""]}
        self.assertRaises(ValueError, parser.Template.resolve_select,
                          join3)

    def test_select_empty_string(self):
        data = {"Fn::Select": ["0", '']}
        self.assertEqual(parser.Template.resolve_select(data), "")
        data = {"Fn::Select": ["1", '']}
        self.assertEqual(parser.Template.resolve_select(data), "")
        data = {"Fn::Select": ["one", '']}
        self.assertEqual(parser.Template.resolve_select(data), "")

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

    def test_split_ok(self):
        data = {"Fn::Split": [";", "foo; bar; achoo"]}
        self.assertEqual(parser.Template.resolve_split(data),
                         ['foo', ' bar', ' achoo'])

    def test_split_no_delim_in_str(self):
        data = {"Fn::Split": [";", "foo, bar, achoo"]}
        self.assertEqual(parser.Template.resolve_split(data),
                         ['foo, bar, achoo'])

    def test_split_no_delim(self):
        data = {"Fn::Split": ["foo, bar, achoo"]}
        self.assertRaises(ValueError, parser.Template.resolve_split, data)

    def test_split_no_list(self):
        data = {"Fn::Split": "foo, bar, achoo"}
        self.assertRaises(TypeError, parser.Template.resolve_split, data)

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

    def test_get_azs(self):
        snippet = {"Fn::GetAZs": ""}
        self.assertEqual(
            parser.Template.resolve_availability_zones(snippet, None),
            ["nova"])

    def test_get_azs_with_stack(self):
        snippet = {"Fn::GetAZs": ""}
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}))
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        fc = fakes.FakeClient()
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(fc)
        self.m.ReplayAll()
        self.assertEqual(
            parser.Template.resolve_availability_zones(snippet, stack),
            ["nova1"])

    def test_replace(self):
        snippet = {"Fn::Replace": [
            {'$var1': 'foo', '%var2%': 'bar'},
            '$var1 is %var2%'
        ]}
        self.assertEqual(
            parser.Template.resolve_replace(snippet),
            'foo is bar')

    def test_replace_list_mapping(self):
        snippet = {"Fn::Replace": [
            ['var1', 'foo', 'var2', 'bar'],
            '$var1 is ${var2}'
        ]}
        self.assertRaises(TypeError, parser.Template.resolve_replace,
                          snippet)

    def test_replace_dict(self):
        snippet = {"Fn::Replace": {}}
        self.assertRaises(TypeError, parser.Template.resolve_replace,
                          snippet)

    def test_replace_missing_template(self):
        snippet = {"Fn::Replace": [['var1', 'foo', 'var2', 'bar']]}
        self.assertRaises(ValueError, parser.Template.resolve_replace,
                          snippet)

    def test_replace_none_template(self):
        snippet = {"Fn::Replace": [['var1', 'foo', 'var2', 'bar'], None]}
        self.assertRaises(TypeError, parser.Template.resolve_replace,
                          snippet)

    def test_replace_list_string(self):
        snippet = {"Fn::Replace": [
            {'var1': 'foo', 'var2': 'bar'},
            ['$var1 is ${var2}']
        ]}
        self.assertRaises(TypeError, parser.Template.resolve_replace,
                          snippet)

    def test_replace_none_values(self):
        snippet = {"Fn::Replace": [
            {'$var1': None, '${var2}': None},
            '"$var1" is "${var2}"'
        ]}
        self.assertEqual(
            parser.Template.resolve_replace(snippet),
            '"" is ""')

    def test_replace_missing_key(self):
        snippet = {"Fn::Replace": [
            {'$var1': 'foo', 'var2': 'bar'},
            '"$var1" is "${var3}"'
        ]}
        self.assertEqual(
            parser.Template.resolve_replace(snippet),
            '"foo" is "${var3}"')

    def test_member_list2map_good(self):
        snippet = {"Fn::MemberListToMap": [
            'Name', 'Value', ['.member.0.Name=metric',
                              '.member.0.Value=cpu',
                              '.member.1.Name=size',
                              '.member.1.Value=56']]}
        self.assertEqual(
            {'metric': 'cpu', 'size': '56'},
            parser.Template.resolve_member_list_to_map(snippet))

    def test_member_list2map_good2(self):
        snippet = {"Fn::MemberListToMap": [
            'Key', 'Value', ['.member.2.Key=metric',
                             '.member.2.Value=cpu',
                             '.member.5.Key=size',
                             '.member.5.Value=56']]}
        self.assertEqual(
            {'metric': 'cpu', 'size': '56'},
            parser.Template.resolve_member_list_to_map(snippet))

    def test_member_list2map_no_key_or_val(self):
        snippet = {"Fn::MemberListToMap": [
            'Key', ['.member.2.Key=metric',
                    '.member.2.Value=cpu',
                    '.member.5.Key=size',
                    '.member.5.Value=56']]}
        self.assertRaises(TypeError,
                          parser.Template.resolve_member_list_to_map,
                          snippet)

    def test_member_list2map_no_list(self):
        snippet = {"Fn::MemberListToMap": [
            'Key', '.member.2.Key=metric']}
        self.assertRaises(TypeError,
                          parser.Template.resolve_member_list_to_map,
                          snippet)

    def test_member_list2map_not_string(self):
        snippet = {"Fn::MemberListToMap": [
            'Name', ['Value'], ['.member.0.Name=metric',
                                '.member.0.Value=cpu',
                                '.member.1.Name=size',
                                '.member.1.Value=56']]}
        self.assertRaises(TypeError,
                          parser.Template.resolve_member_list_to_map,
                          snippet)

    def test_resource_facade(self):
        metadata_snippet = {'Fn::ResourceFacade': 'Metadata'}
        deletion_policy_snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}
        update_policy_snippet = {'Fn::ResourceFacade': 'UpdatePolicy'}

        class DummyClass(object):
            pass
        parent_resource = DummyClass()
        parent_resource.metadata = '{"foo": "bar"}'
        parent_resource.t = {'DeletionPolicy': 'Retain',
                             'UpdatePolicy': '{"foo": "bar"}'}
        parent_resource.stack = parser.Stack(self.ctx, 'toplevel_stack',
                                             parser.Template({}))
        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template({}),
                             parent_resource=parent_resource)
        self.assertEqual(
            parser.Template.resolve_resource_facade(metadata_snippet, stack),
            '{"foo": "bar"}')
        self.assertEqual(
            parser.Template.resolve_resource_facade(deletion_policy_snippet,
                                                    stack), 'Retain')
        self.assertEqual(
            parser.Template.resolve_resource_facade(update_policy_snippet,
                                                    stack), '{"foo": "bar"}')

    def test_resource_facade_invalid_arg(self):
        snippet = {'Fn::ResourceFacade': 'wibble'}
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}))
        self.assertRaises(ValueError,
                          parser.Template.resolve_resource_facade,
                          snippet,
                          stack)

    def test_resource_facade_missing_key(self):
        snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}

        class DummyClass(object):
            pass
        parent_resource = DummyClass()
        parent_resource.metadata = '{"foo": "bar"}'
        parent_resource.t = {}
        parent_resource.stack = parser.Stack(self.ctx, 'toplevel_stack',
                                             parser.Template({}))
        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template({}),
                             parent_resource=parent_resource)
        self.assertRaises(KeyError,
                          parser.Template.resolve_resource_facade,
                          snippet,
                          stack)


class StackTest(HeatTestCase):
    def setUp(self):
        super(StackTest, self).setUp()

        self.username = 'parser_stack_test_user'

        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithPropsType',
                                 generic_rsrc.ResourceWithProps)

        self.m.ReplayAll()

    def test_state_defaults(self):
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}))
        self.assertEqual(stack.state, (None, None))
        self.assertEqual(stack.status_reason, '')

    def test_no_auth_token(self):
        ctx = utils.dummy_context()
        ctx.auth_token = None
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        clients.OpenStackClients.keystone().MultipleTimes().AndReturn(
            FakeKeystoneClient())

        self.m.ReplayAll()
        stack = parser.Stack(ctx, 'test_stack', parser.Template({}))
        self.assertEqual('abcd1234', stack.clients.auth_token)

        self.m.VerifyAll()

    def test_state(self):
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}),
                             action=parser.Stack.CREATE,
                             status=parser.Stack.IN_PROGRESS)
        self.assertEqual(stack.state,
                         (parser.Stack.CREATE, parser.Stack.IN_PROGRESS))
        stack.state_set(parser.Stack.CREATE, parser.Stack.COMPLETE, 'test')
        self.assertEqual(stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))
        stack.state_set(parser.Stack.DELETE, parser.Stack.COMPLETE, 'test')
        self.assertEqual(stack.state,
                         (parser.Stack.DELETE, parser.Stack.COMPLETE))

    def test_state_bad(self):
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}),
                             action=parser.Stack.CREATE,
                             status=parser.Stack.IN_PROGRESS)
        self.assertEqual(stack.state,
                         (parser.Stack.CREATE, parser.Stack.IN_PROGRESS))
        self.assertRaises(ValueError, stack.state_set,
                          'baad', parser.Stack.COMPLETE, 'test')
        self.assertRaises(ValueError, stack.state_set,
                          parser.Stack.CREATE, 'oops', 'test')

    def test_status_reason(self):
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}),
                             status_reason='quux')
        self.assertEqual(stack.status_reason, 'quux')
        stack.state_set(parser.Stack.CREATE, parser.Stack.IN_PROGRESS,
                        'wibble')
        self.assertEqual(stack.status_reason, 'wibble')

    def test_load_nonexistant_id(self):
        self.assertRaises(exception.NotFound, parser.Stack.load,
                          None, -1)

    def test_total_resources_empty(self):
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}),
                             status_reason='flimflam')
        self.assertEqual(0, stack.total_resources())

    def test_total_resources_generic(self):
        tpl = {'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template(tpl),
                             status_reason='blarg')
        self.assertEqual(1, stack.total_resources())

    def _setup_nested(self, name):
        nested_tpl = ('{"Resources":{'
                      '"A": {"Type": "GenericResourceType"},'
                      '"B": {"Type": "GenericResourceType"}}}')
        tpl = {'Resources':
               {'A': {'Type': 'AWS::CloudFormation::Stack',
                      'Properties':
                      {'TemplateURL': 'http://server.test/nested.json'}},
                'B': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(urlfetch, 'get')
        urlfetch.get('http://server.test/nested.json').AndReturn(nested_tpl)
        self.m.ReplayAll()
        self.stack = parser.Stack(self.ctx, 'test_stack', parser.Template(tpl),
                                  status_reason=name)
        self.stack.store()
        self.stack.create()

    @utils.stack_delete_after
    def test_total_resources_nested(self):
        self._setup_nested('zyzzyx')
        self.assertEqual(4, self.stack.total_resources())
        self.assertNotEqual(None, self.stack.resources['A'].nested())
        self.assertEqual(
            2, self.stack.resources['A'].nested().total_resources())
        self.assertEqual(
            4,
            self.stack.resources['A'].nested().root_stack.total_resources())

    @utils.stack_delete_after
    def test_root_stack(self):
        self._setup_nested('toor')
        self.assertEqual(self.stack, self.stack.root_stack)
        self.assertNotEqual(None, self.stack.resources['A'].nested())
        self.assertEqual(
            self.stack, self.stack.resources['A'].nested().root_stack)

    @utils.stack_delete_after
    def test_load_parent_resource(self):
        self.stack = parser.Stack(self.ctx, 'load_parent_resource',
                                  parser.Template({}))
        self.stack.store()
        stack = db_api.stack_get(self.ctx, self.stack.id)

        t = template.Template.load(self.ctx, stack.raw_template_id)
        self.m.StubOutWithMock(template.Template, 'load')
        template.Template.load(self.ctx, stack.raw_template_id).AndReturn(t)

        env = environment.Environment(stack.parameters)
        self.m.StubOutWithMock(environment, 'Environment')
        environment.Environment(stack.parameters).AndReturn(env)

        self.m.StubOutWithMock(parser.Stack, '__init__')
        parser.Stack.__init__(self.ctx, stack.name, t, env, stack.id,
                              stack.action, stack.status, stack.status_reason,
                              stack.timeout, True, stack.disable_rollback,
                              'parent', owner_id=None)

        self.m.ReplayAll()
        parser.Stack.load(self.ctx, stack_id=self.stack.id,
                          parent_resource='parent')

        self.m.VerifyAll()

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the self.stack is properly cleaned up
    @utils.stack_delete_after
    def test_identifier(self):
        self.stack = parser.Stack(self.ctx, 'identifier_test',
                                  parser.Template({}))
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(identifier.tenant, self.ctx.tenant_id)
        self.assertEqual(identifier.stack_name, 'identifier_test')
        self.assertTrue(identifier.stack_id)
        self.assertFalse(identifier.path)

    @utils.stack_delete_after
    def test_set_param_id(self):
        self.stack = parser.Stack(self.ctx, 'param_arn_test',
                                  parser.Template({}))
        exp_prefix = ('arn:openstack:heat::test_tenant_id'
                      ':stacks/param_arn_test/')
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         exp_prefix + 'None')
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         exp_prefix + self.stack.id)
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         identifier.arn())
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_load_param_id(self):
        self.stack = parser.Stack(self.ctx, 'param_load_arn_test',
                                  parser.Template({}))
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         identifier.arn())

        newstack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(newstack.parameters['AWS::StackId'], identifier.arn())

    @utils.stack_delete_after
    def test_created_time(self):
        self.stack = parser.Stack(self.ctx, 'creation_time_test',
                                  parser.Template({}))
        self.assertEqual(self.stack.created_time, None)
        self.stack.store()
        self.assertNotEqual(self.stack.created_time, None)

    @utils.stack_delete_after
    def test_updated_time(self):
        self.stack = parser.Stack(self.ctx, 'update_time_test',
                                  parser.Template({}))
        self.assertEqual(self.stack.updated_time, None)
        self.stack.store()
        stored_time = self.stack.updated_time
        self.stack.state_set(self.stack.CREATE, self.stack.IN_PROGRESS, 'test')
        self.assertNotEqual(self.stack.updated_time, None)
        self.assertNotEqual(self.stack.updated_time, stored_time)

    @utils.stack_delete_after
    def test_delete(self):
        self.stack = parser.Stack(self.ctx, 'delete_test',
                                  parser.Template({}))
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertEqual(db_s, None)
        self.assertEqual(self.stack.state,
                         (parser.Stack.DELETE, parser.Stack.COMPLETE))

    @utils.stack_delete_after
    def test_delete_trust(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        clients.OpenStackClients.keystone().MultipleTimes().AndReturn(
            FakeKeystoneClient())
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'delete_trust', template.Template({}))
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertEqual(db_s, None)
        self.assertEqual(self.stack.state,
                         (parser.Stack.DELETE, parser.Stack.COMPLETE))

    @utils.stack_delete_after
    def test_delete_trust_fail(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        class FakeKeystoneClientFail(FakeKeystoneClient):
            def delete_trust(self, trust_id):
                raise kc_exceptions.Forbidden("Denied!")

        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        clients.OpenStackClients.keystone().MultipleTimes().AndReturn(
            FakeKeystoneClientFail())
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'delete_trust', template.Template({}))
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertEqual(self.stack.state,
                         (parser.Stack.DELETE, parser.Stack.FAILED))
        self.assertIn('Error deleting trust', self.stack.status_reason)

    @utils.stack_delete_after
    def test_suspend_resume(self):
        self.m.ReplayAll()
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = parser.Stack(self.ctx, 'suspend_test',
                                  parser.Template(tmpl))
        stack_id = self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (self.stack.CREATE, self.stack.COMPLETE))

        self.stack.suspend()

        self.assertEqual(self.stack.state,
                         (self.stack.SUSPEND, self.stack.COMPLETE))

        self.stack.resume()

        self.assertEqual(self.stack.state,
                         (self.stack.RESUME, self.stack.COMPLETE))

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_suspend_fail(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_suspend')
        exc = Exception('foo')
        generic_rsrc.GenericResource.handle_suspend().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'suspend_test_fail',
                                  parser.Template(tmpl))

        stack_id = self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (self.stack.CREATE, self.stack.COMPLETE))

        self.stack.suspend()

        self.assertEqual(self.stack.state,
                         (self.stack.SUSPEND, self.stack.FAILED))
        self.assertEqual(self.stack.status_reason,
                         'Resource suspend failed: Exception: foo')
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_resume_fail(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_resume')
        generic_rsrc.GenericResource.handle_resume().AndRaise(Exception('foo'))
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'resume_test_fail',
                                  parser.Template(tmpl))

        stack_id = self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (self.stack.CREATE, self.stack.COMPLETE))

        self.stack.suspend()

        self.assertEqual(self.stack.state,
                         (self.stack.SUSPEND, self.stack.COMPLETE))

        self.stack.resume()

        self.assertEqual(self.stack.state,
                         (self.stack.RESUME, self.stack.FAILED))
        self.assertEqual(self.stack.status_reason,
                         'Resource resume failed: Exception: foo')
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_suspend_timeout(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_suspend')
        exc = scheduler.Timeout('foo', 0)
        generic_rsrc.GenericResource.handle_suspend().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'suspend_test_fail_timeout',
                                  parser.Template(tmpl))

        stack_id = self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (self.stack.CREATE, self.stack.COMPLETE))

        self.stack.suspend()

        self.assertEqual(self.stack.state,
                         (self.stack.SUSPEND, self.stack.FAILED))
        self.assertEqual(self.stack.status_reason, 'Suspend timed out')
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_resume_timeout(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_resume')
        exc = scheduler.Timeout('foo', 0)
        generic_rsrc.GenericResource.handle_resume().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'resume_test_fail_timeout',
                                  parser.Template(tmpl))

        stack_id = self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (self.stack.CREATE, self.stack.COMPLETE))

        self.stack.suspend()

        self.assertEqual(self.stack.state,
                         (self.stack.SUSPEND, self.stack.COMPLETE))

        self.stack.resume()

        self.assertEqual(self.stack.state,
                         (self.stack.RESUME, self.stack.FAILED))

        self.assertEqual(self.stack.status_reason, 'Resume timed out')
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_delete_rollback(self):
        self.stack = parser.Stack(self.ctx, 'delete_rollback_test',
                                  parser.Template({}), disable_rollback=False)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.stack.delete(action=self.stack.ROLLBACK)

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertEqual(db_s, None)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.COMPLETE))

    @utils.stack_delete_after
    def test_delete_badaction(self):
        self.stack = parser.Stack(self.ctx, 'delete_badaction_test',
                                  parser.Template({}))
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.stack.delete(action="wibble")

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)
        self.assertEqual(self.stack.state,
                         (parser.Stack.DELETE, parser.Stack.FAILED))

    @utils.stack_delete_after
    def test_update_badstate(self):
        self.stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}),
                                  action=parser.Stack.CREATE,
                                  status=parser.Stack.FAILED)
        stack_id = self.stack.store()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.FAILED))
        self.stack.update({})
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.FAILED))

    @utils.stack_delete_after
    def test_resource_by_refid(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'resource_by_refid_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))
        self.assertTrue('AResource' in self.stack)
        rsrc = self.stack['AResource']
        rsrc.resource_id_set('aaaa')
        self.assertNotEqual(None, resource)

        for action, status in (
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
            self.assertEqual(None, self.stack.resource_by_refid('aaaa'))
            self.assertEqual(None, self.stack.resource_by_refid('bbbb'))
        finally:
            rsrc.state_set(rsrc.CREATE, rsrc.COMPLETE)

    @utils.stack_delete_after
    def test_update_add(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.COMPLETE))
        self.assertTrue('BResource' in self.stack)

    @utils.stack_delete_after
    def test_update_remove(self):
        tmpl = {'Resources': {
                'AResource': {'Type': 'GenericResourceType'},
                'BResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.COMPLETE))
        self.assertFalse('BResource' in self.stack)

    @utils.stack_delete_after
    def test_update_description(self):
        tmpl = {'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Description': 'BTemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack.t[template.DESCRIPTION], 'BTemplate')

    @utils.stack_delete_after
    def test_update_modify_ok_replace(self):
        tmpl = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # Calls to GenericResource.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'xyz')
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_modify_update_failed(self):
        tmpl = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        res = self.stack['AResource']
        res.update_allowed_keys = ('Properties',)
        res.update_allowed_properties = ('Foo',)

        tmpl2 = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_update
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        generic_rsrc.ResourceWithProps.handle_update(
            tmpl2['Resources']['AResource'], tmpl_diff,
            prop_diff).AndRaise(Exception("Foo"))
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.FAILED))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_modify_replace_failed_delete(self):
        tmpl = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # Calls to GenericResource.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties

        # make the update fail deleting the existing resource
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.FAILED))
        self.m.VerifyAll()
        # Unset here so destroy() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    @utils.stack_delete_after
    def test_update_modify_replace_failed_create(self):
        tmpl = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # Calls to GenericResource.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties

        # patch in a dummy handle_create making the replace fail creating
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.FAILED))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_add_failed_create(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

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
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.FAILED))
        self.assertTrue('BResource' in self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertTrue('BResource' in re_stack)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_rollback(self):
        tmpl = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # Calls to GenericResource.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_rollback_fail(self):
        tmpl = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # Calls to GenericResource.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc, and again on the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.FAILED))
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_rollback_add(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc, and succeed on the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.COMPLETE))
        self.assertFalse('BResource' in self.stack)
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_rollback_remove(self):
        tmpl = {'Resources': {
                'AResource': {'Type': 'GenericResourceType'},
                'BResource': {'Type': 'ResourceWithPropsType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy delete making the destroy fail
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.COMPLETE))
        self.assertTrue('BResource' in self.stack)
        self.m.VerifyAll()
        # Unset here so delete() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    @utils.stack_delete_after
    def test_update_rollback_replace(self):
        tmpl = {'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'foo'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        tmpl2 = {'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'bar'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy delete making the destroy fail
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.COMPLETE))
        self.m.VerifyAll()
        # Unset here so delete() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    @utils.stack_delete_after
    def test_update_replace_by_reference(self):
        '''
        assertion:
        changes in dynamic attributes, due to other resources been updated
        are not ignored and can cause dependant resources to be updated.
        '''
        tmpl = {'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {
                              'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                               'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))

        self.m.ReplayAll()

        self.stack.store()
        self.stack.create()
        self.m.VerifyAll()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.assertEqual(self.stack['BResource'].properties['Foo'],
                         'AResource')

        # Calls to GenericResource.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'FnGetRefId')
        generic_rsrc.ResourceWithProps.FnGetRefId().AndReturn(
            'AResource')
        generic_rsrc.ResourceWithProps.FnGetRefId().MultipleTimes().AndReturn(
            'inst-007')
        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'smelly')
        self.assertEqual(self.stack['BResource'].properties['Foo'], 'inst-007')
        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_by_reference_and_rollback_1(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the first instance
        '''
        tmpl = {'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {
                              'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                               'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)

        self.m.ReplayAll()

        self.stack.store()
        self.stack.create()
        self.m.VerifyAll()

        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.assertEqual(self.stack['BResource'].properties['Foo'],
                         'AResource')

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'FnGetRefId')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        # Calls to ResourceWithProps.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties

        generic_rsrc.ResourceWithProps.FnGetRefId().MultipleTimes().AndReturn(
            'AResource')

        # mock to make the replace fail when creating the replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_by_reference_and_rollback_2(self):
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

        resource._register_class('ResourceTypeA', ResourceTypeA)

        tmpl = {'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {
                              'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'Resources': {
                 'AResource': {'Type': 'ResourceTypeA',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                               'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)

        self.m.ReplayAll()

        self.stack.store()
        self.stack.create()
        self.m.VerifyAll()

        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.assertEqual(self.stack['BResource'].properties['Foo'],
                         'AResource1')

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        # Calls to ResourceWithProps.handle_update will raise
        # resource.UpdateReplace because we've not specified the modified
        # key/property in update_allowed_keys/update_allowed_properties

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.ROLLBACK, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')
        self.assertEqual(self.stack['BResource'].properties['Foo'],
                         'AResource1')

        self.m.VerifyAll()

    @utils.stack_delete_after
    def test_update_replace_parameters(self):
        '''
        assertion:
        changes in static environment parameters
        are not ignored and can cause dependant resources to be updated.
        '''
        tmpl = {'Parameters': {'AParam': {'Type': 'String'}},
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': {'Ref': 'AParam'}}}}}

        env1 = {'parameters': {'AParam': 'abc'}}
        env2 = {'parameters': {'AParam': 'smelly'}}
        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  environment.Environment(env1))

        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'abc')

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl),
                                     environment.Environment(env2))
        self.stack.update(updated_stack)
        self.assertEqual(self.stack.state,
                         (parser.Stack.UPDATE, parser.Stack.COMPLETE))
        self.assertEqual(self.stack['AResource'].properties['Foo'], 'smelly')

    def test_stack_create_timeout(self):
        self.m.StubOutWithMock(scheduler.DependencyTaskGroup, '__call__')
        self.m.StubOutWithMock(scheduler, 'wallclock')

        stack = parser.Stack(self.ctx, 's', parser.Template({}))

        def dummy_task():
            while True:
                yield

        start_time = time.time()
        scheduler.wallclock().AndReturn(start_time)
        scheduler.wallclock().AndReturn(start_time + 1)
        scheduler.DependencyTaskGroup.__call__().AndReturn(dummy_task())
        scheduler.wallclock().AndReturn(start_time + stack.timeout_secs() + 1)

        self.m.ReplayAll()

        stack.create()

        self.assertEqual(stack.state,
                         (parser.Stack.CREATE, parser.Stack.FAILED))
        self.assertEqual(stack.status_reason, 'Create timed out')

        self.m.VerifyAll()

    def test_stack_delete_timeout(self):
        stack = parser.Stack(self.ctx, 'delete_test',
                             parser.Template({}))
        stack_id = stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertNotEqual(db_s, None)

        self.m.StubOutWithMock(scheduler.DependencyTaskGroup, '__call__')
        self.m.StubOutWithMock(scheduler, 'wallclock')

        def dummy_task():
            while True:
                yield

        start_time = time.time()
        scheduler.wallclock().AndReturn(start_time)
        scheduler.wallclock().AndReturn(start_time + 1)
        scheduler.DependencyTaskGroup.__call__().AndReturn(dummy_task())
        scheduler.wallclock().AndReturn(start_time + stack.timeout_secs() + 1)
        self.m.ReplayAll()
        stack.delete()

        self.assertEqual(stack.state,
                         (parser.Stack.DELETE, parser.Stack.FAILED))
        self.assertEqual(stack.status_reason, 'Delete timed out')

        self.m.VerifyAll()

    def test_stack_delete_resourcefailure(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_delete')
        exc = Exception('foo')
        generic_rsrc.GenericResource.handle_delete().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'delete_test_fail',
                                  parser.Template(tmpl))

        stack_id = self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (self.stack.CREATE, self.stack.COMPLETE))

        self.stack.delete()

        self.assertEqual(self.stack.state,
                         (self.stack.DELETE, self.stack.FAILED))
        self.assertEqual(self.stack.status_reason,
                         'Resource delete failed: Exception: foo')
        self.m.VerifyAll()

    def test_stack_name_valid(self):
        stack = parser.Stack(self.ctx, 's', parser.Template({}))
        stack = parser.Stack(self.ctx, 'stack123', parser.Template({}))
        stack = parser.Stack(self.ctx, 'test.stack', parser.Template({}))
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template({}))
        stack = parser.Stack(self.ctx, 'TEST', parser.Template({}))
        stack = parser.Stack(self.ctx, 'test-stack', parser.Template({}))

    def test_stack_name_invalid(self):
        self.assertRaises(ValueError, parser.Stack, self.ctx, '_foo',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, '1bad',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, '.kcats',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, ' teststack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, '^-^',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, '\"stack\"',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, '1234',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'cat|dog',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, '$(foo)',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test/stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test\stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test::stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test;stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test~stack',
                          parser.Template({}))
        self.assertRaises(ValueError, parser.Stack, self.ctx, '#test',
                          parser.Template({}))

    @utils.stack_delete_after
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
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))
        self.assertTrue('AResource' in self.stack)
        rsrc = self.stack['AResource']
        rsrc.resource_id_set('aaaa')
        self.assertEqual('AResource', rsrc.FnGetAtt('Foo'))

        for action, status in (
                (rsrc.CREATE, rsrc.IN_PROGRESS),
                (rsrc.CREATE, rsrc.COMPLETE),
                (rsrc.RESUME, rsrc.IN_PROGRESS),
                (rsrc.RESUME, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.IN_PROGRESS),
                (rsrc.UPDATE, rsrc.COMPLETE)):
            rsrc.state_set(action, status)
            self.assertEqual('AResource', self.stack.output('TestOutput'))
        for action, status in (
                (rsrc.CREATE, rsrc.FAILED),
                (rsrc.DELETE, rsrc.IN_PROGRESS),
                (rsrc.DELETE, rsrc.FAILED),
                (rsrc.DELETE, rsrc.COMPLETE),
                (rsrc.UPDATE, rsrc.FAILED)):
            rsrc.state_set(action, status)
            self.assertEqual(None, self.stack.output('TestOutput'))

    @utils.stack_delete_after
    def test_resource_required_by(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'},
                              'BResource': {'Type': 'GenericResourceType',
                                            'DependsOn': 'AResource'},
                              'CResource': {'Type': 'GenericResourceType',
                                            'DependsOn': 'BResource'},
                              'DResource': {'Type': 'GenericResourceType',
                                            'DependsOn': 'BResource'}}}

        self.stack = parser.Stack(self.ctx, 'depends_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        self.assertEqual(['BResource'],
                         self.stack['AResource'].required_by())
        self.assertEqual([],
                         self.stack['CResource'].required_by())
        required_by = self.stack['BResource'].required_by()
        self.assertEqual(2, len(required_by))
        for r in ['CResource', 'DResource']:
            self.assertIn(r, required_by)

    @utils.stack_delete_after
    def test_resource_multi_required_by(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'},
                              'BResource': {'Type': 'GenericResourceType'},
                              'CResource': {'Type': 'GenericResourceType'},
                              'DResource': {'Type': 'GenericResourceType',
                                            'DependsOn': ['AResource',
                                                          'BResource',
                                                          'CResource']}}}

        self.stack = parser.Stack(self.ctx, 'depends_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        for r in ['AResource', 'BResource', 'CResource']:
            self.assertEqual(['DResource'],
                             self.stack[r].required_by())

    @utils.stack_delete_after
    def test_store_saves_owner(self):
        """
        The owner_id attribute of Store is saved to the database when stored.
        """
        self.stack = parser.Stack(
            self.ctx, 'owner_stack', template.Template({}))
        stack_ownee = parser.Stack(
            self.ctx, 'ownee_stack', template.Template({}),
            owner_id=self.stack.id)
        stack_ownee.store()
        db_stack = db_api.stack_get(self.ctx, stack_ownee.id)
        self.assertEqual(db_stack.owner_id, self.stack.id)

    @utils.stack_delete_after
    def test_store_saves_creds(self):
        """
        A user_creds entry is created on first stack store
        """
        self.stack = parser.Stack(
            self.ctx, 'creds_stack', template.Template({}))
        self.stack.store()

        # The store should've created a user_creds row and set user_creds_id
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        user_creds_id = db_stack.user_creds_id
        self.assertIsNotNone(user_creds_id)

        # should've stored the username/password in the context
        user_creds = db_api.user_creds_get(user_creds_id)
        self.assertEqual(self.ctx.username, user_creds.get('username'))
        self.assertEqual(self.ctx.password, user_creds.get('password'))
        self.assertIsNone(user_creds.get('trust_id'))
        self.assertIsNone(user_creds.get('trustor_user_id'))

        # Store again, ID should not change
        self.stack.store()
        self.assertEqual(user_creds_id, db_stack.user_creds_id)

    @utils.stack_delete_after
    def test_store_saves_creds_trust(self):
        """
        A user_creds entry is created on first stack store
        """
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        clients.OpenStackClients.keystone().MultipleTimes().AndReturn(
            FakeKeystoneClient())
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'creds_stack', template.Template({}))
        self.stack.store()

        # The store should've created a user_creds row and set user_creds_id
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        user_creds_id = db_stack.user_creds_id
        self.assertIsNotNone(user_creds_id)

        # should've stored the trust_id and trustor_user_id returned from
        # FakeKeystoneClient.create_trust_context, username/password should
        # not have been stored
        user_creds = db_api.user_creds_get(user_creds_id)
        self.assertIsNone(user_creds.get('username'))
        self.assertIsNone(user_creds.get('password'))
        self.assertEqual('atrust', user_creds.get('trust_id'))
        self.assertEqual('auser123', user_creds.get('trustor_user_id'))

        # Store again, ID should not change
        self.stack.store()
        self.assertEqual(user_creds_id, db_stack.user_creds_id)

    @utils.stack_delete_after
    def test_load_honors_owner(self):
        """
        Loading a stack from the database will set the owner_id of the
        resultant stack appropriately.
        """
        self.stack = parser.Stack(
            self.ctx, 'owner_stack', template.Template({}))
        stack_ownee = parser.Stack(
            self.ctx, 'ownee_stack', template.Template({}),
            owner_id=self.stack.id)
        stack_ownee.store()

        saved_stack = parser.Stack.load(self.ctx, stack_id=stack_ownee.id)
        self.assertEqual(saved_stack.owner_id, self.stack.id)

    @utils.stack_delete_after
    def test_requires_deferred_auth(self):
        tmpl = {'Resources': {'AResource': {'Type': 'GenericResourceType'},
                              'BResource': {'Type': 'GenericResourceType'},
                              'CResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)

        self.assertFalse(self.stack.requires_deferred_auth())

        self.stack['CResource'].requires_deferred_auth = True
        self.assertTrue(self.stack.requires_deferred_auth())
