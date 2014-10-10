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

from keystoneclient import exceptions as kc_exceptions
import mock
from mox import IgnoreArg
from oslo.config import cfg
import six
import warnings

from heat.common import context
from heat.common import exception
from heat.common import heat_keystoneclient as hkc
from heat.common import template_format
from heat.common import urlfetch
import heat.db.api as db_api
import heat.engine.cfn.functions
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.cfn import template as cfn_t
from heat.engine.clients.os import keystone
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine import function
from heat.engine.hot import template as hot_t
from heat.engine import parameters
from heat.engine import parser
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests.fakes import FakeKeystoneClient
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils
from heat.tests.v1_1 import fakes


def join(raw):
    tmpl = template.Template(mapping_template)
    return function.resolve(tmpl.parse(None, raw))


class ParserTest(HeatTestCase):

    def test_list(self):
        raw = ['foo', 'bar', 'baz']
        parsed = join(raw)
        for i in six.moves.xrange(len(raw)):
            self.assertEqual(raw[i], parsed[i])
        self.assertIsNot(raw, parsed)

    def test_dict(self):
        raw = {'foo': 'bar', 'blarg': 'wibble'}
        parsed = join(raw)
        for k in raw:
            self.assertEqual(raw[k], parsed[k])
        self.assertIsNot(raw, parsed)

    def test_dict_list(self):
        raw = {'foo': ['bar', 'baz'], 'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual(raw['blarg'], parsed['blarg'])
        for i in six.moves.xrange(len(raw['foo'])):
            self.assertEqual(raw['foo'][i], parsed['foo'][i])
        self.assertIsNot(raw, parsed)
        self.assertIsNot(raw['foo'], parsed['foo'])

    def test_list_dict(self):
        raw = [{'foo': 'bar', 'blarg': 'wibble'}, 'baz', 'quux']
        parsed = join(raw)
        for i in six.moves.xrange(1, len(raw)):
            self.assertEqual(raw[i], parsed[i])
        for k in raw[0]:
            self.assertEqual(raw[0][k], parsed[0][k])
        self.assertIsNot(raw, parsed)
        self.assertIsNot(raw[0], parsed[0])

    def test_join(self):
        raw = {'Fn::Join': [' ', ['foo', 'bar', 'baz']]}
        self.assertEqual('foo bar baz', join(raw))

    def test_join_none(self):
        raw = {'Fn::Join': [' ', ['foo', None, 'baz']]}
        self.assertEqual('foo  baz', join(raw))

    def test_join_list(self):
        raw = [{'Fn::Join': [' ', ['foo', 'bar', 'baz']]}, 'blarg', 'wibble']
        parsed = join(raw)
        self.assertEqual('foo bar baz', parsed[0])
        for i in six.moves.xrange(1, len(raw)):
            self.assertEqual(raw[i], parsed[i])
        self.assertIsNot(raw, parsed)

    def test_join_dict_val(self):
        raw = {'quux': {'Fn::Join': [' ', ['foo', 'bar', 'baz']]},
               'blarg': 'wibble'}
        parsed = join(raw)
        self.assertEqual('foo bar baz', parsed['quux'])
        self.assertEqual(raw['blarg'], parsed['blarg'])
        self.assertIsNot(raw, parsed)


mapping_template = template_format.parse('''{
  "AWSTemplateFormatVersion" : "2010-09-09",
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

empty_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
}''')

parameter_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
  "Parameters" : {
    "foo" : { "Type" : "String" },
    "blarg" : { "Type" : "String", "Default": "quux" }
  }
}''')


resource_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
  "Resources" : {
    "foo" : { "Type" : "GenericResourceType" },
    "blarg" : { "Type" : "GenericResourceType" }
  }
}''')


class DummyClass(object):
    metadata = None

    def metadata_get(self):
        return self.metadata

    def metadata_set(self, metadata):
        self.metadata = metadata


class TemplateTest(HeatTestCase):

    def setUp(self):
        super(TemplateTest, self).setUp()
        self.ctx = utils.dummy_context()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)

    @staticmethod
    def resolve(snippet, template, stack=None):
        return function.resolve(template.parse(stack, snippet))

    def test_defaults(self):
        empty = parser.Template(empty_template)
        self.assertNotIn('AWSTemplateFormatVersion', empty)
        self.assertEqual('No description', empty['Description'])
        self.assertEqual({}, empty['Mappings'])
        self.assertEqual({}, empty['Resources'])
        self.assertEqual({}, empty['Outputs'])

    def test_aws_version(self):
        tmpl = parser.Template(mapping_template)
        self.assertEqual(('AWSTemplateFormatVersion', '2010-09-09'),
                         tmpl.version)

    def test_heat_version(self):
        tmpl = parser.Template(resource_template)
        self.assertEqual(('HeatTemplateFormatVersion', '2012-12-12'),
                         tmpl.version)

    def test_invalid_hot_version(self):
        invalid_hot_version_tmp = template_format.parse(
            '''{
            "heat_template_version" : "2012-12-12",
            }''')
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    parser.Template, invalid_hot_version_tmp)
        valid_versions = ['2014-10-16', '2013-05-23']
        ex_error_msg = ('The template version is invalid: '
                        '"heat_template_version: 2012-12-12". '
                        '"heat_template_version" should be one of: %s'
                        % ', '.join(valid_versions))
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

    def test_invalid_version_not_in_hot_versions(self):
        invalid_hot_version_tmp = template_format.parse(
            '''{
            "heat_template_version" : "2012-12-12",
            }''')
        versions = {
            ('heat_template_version', '2013-05-23'): hot_t.HOTemplate20130523,
            ('heat_template_version', '2013-06-23'): hot_t.HOTemplate20130523
        }

        temp_copy = copy.deepcopy(template._template_classes)
        template._template_classes = versions
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    parser.Template, invalid_hot_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"heat_template_version: 2012-12-12". '
                        '"heat_template_version" should be '
                        'one of: 2013-05-23, 2013-06-23')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))
        template._template_classes = temp_copy

    def test_invalid_aws_version(self):
        invalid_aws_version_tmp = template_format.parse(
            '''{
            "AWSTemplateFormatVersion" : "2012-12-12",
            }''')
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    parser.Template, invalid_aws_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"AWSTemplateFormatVersion: 2012-12-12". '
                        '"AWSTemplateFormatVersion" should be: 2010-09-09')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

    def test_invalid_version_not_in_aws_versions(self):
        invalid_aws_version_tmp = template_format.parse(
            '''{
            "AWSTemplateFormatVersion" : "2012-12-12",
            }''')
        versions = {
            ('AWSTemplateFormatVersion', '2010-09-09'): cfn_t.CfnTemplate,
            ('AWSTemplateFormatVersion', '2011-06-23'): cfn_t.CfnTemplate
        }
        temp_copy = copy.deepcopy(template._template_classes)
        template._template_classes = versions

        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    parser.Template, invalid_aws_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"AWSTemplateFormatVersion: 2012-12-12". '
                        '"AWSTemplateFormatVersion" should be '
                        'one of: 2010-09-09, 2011-06-23')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))
        template._template_classes = temp_copy

    def test_invalid_heat_version(self):
        invalid_heat_version_tmp = template_format.parse(
            '''{
            "HeatTemplateFormatVersion" : "2010-09-09",
            }''')
        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    parser.Template, invalid_heat_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"HeatTemplateFormatVersion: 2010-09-09". '
                        '"HeatTemplateFormatVersion" should be: 2012-12-12')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

    def test_invalid_version_not_in_heat_versions(self):
        invalid_heat_version_tmp = template_format.parse(
            '''{
            "HeatTemplateFormatVersion" : "2010-09-09",
            }''')
        versions = {
            ('HeatTemplateFormatVersion', '2012-12-12'): cfn_t.CfnTemplate,
            ('HeatTemplateFormatVersion', '2014-12-12'): cfn_t.CfnTemplate
        }
        temp_copy = copy.deepcopy(template._template_classes)
        template._template_classes = versions

        init_ex = self.assertRaises(exception.InvalidTemplateVersion,
                                    parser.Template, invalid_heat_version_tmp)
        ex_error_msg = ('The template version is invalid: '
                        '"HeatTemplateFormatVersion: 2010-09-09". '
                        '"HeatTemplateFormatVersion" should be '
                        'one of: 2012-12-12, 2014-12-12')
        self.assertEqual(ex_error_msg, six.text_type(init_ex))

        template._template_classes = temp_copy

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
        tmpl = parser.Template({'HeatTemplateFormatVersion': '2012-12-12',
                                'Foo': ['Bar']})
        self.assertNotIn('Foo', tmpl)

    def test_find_in_map(self):
        tmpl = parser.Template(mapping_template)
        stack = parser.Stack(self.ctx, 'test', tmpl)
        find = {'Fn::FindInMap': ["ValidMapping", "TestKey", "TestValue"]}
        self.assertEqual("wibble", self.resolve(find, tmpl, stack))

    def test_find_in_invalid_map(self):
        tmpl = parser.Template(mapping_template)
        stack = parser.Stack(self.ctx, 'test', tmpl)
        finds = ({'Fn::FindInMap': ["InvalidMapping", "ValueList", "foo"]},
                 {'Fn::FindInMap': ["InvalidMapping", "ValueString", "baz"]},
                 {'Fn::FindInMap': ["MapList", "foo", "bar"]},
                 {'Fn::FindInMap': ["MapString", "foo", "bar"]})

        for find in finds:
            self.assertRaises((KeyError, TypeError), self.resolve,
                              find, tmpl, stack)

    def test_bad_find_in_map(self):
        tmpl = parser.Template(mapping_template)
        stack = parser.Stack(self.ctx, 'test', tmpl)
        finds = ({'Fn::FindInMap': "String"},
                 {'Fn::FindInMap': {"Dict": "String"}},
                 {'Fn::FindInMap': ["ShortList", "foo"]},
                 {'Fn::FindInMap': ["ReallyShortList"]})

        for find in finds:
            self.assertRaises(KeyError, self.resolve, find, tmpl, stack)

    def test_param_refs(self):
        tmpl = parser.Template(parameter_template)
        env = environment.Environment({'foo': 'bar', 'blarg': 'wibble'})
        stack = parser.Stack(self.ctx, 'test', tmpl, env)
        p_snippet = {"Ref": "foo"}
        self.assertEqual("bar", self.resolve(p_snippet, tmpl, stack))

    def test_param_ref_missing(self):
        tmpl = parser.Template(parameter_template)
        env = environment.Environment({'foo': 'bar'})
        stack = parser.Stack(self.ctx, 'test', tmpl, env)
        stack.env = environment.Environment({})
        stack.parameters = parameters.Parameters(stack.identifier(), tmpl)
        snippet = {"Ref": "foo"}
        self.assertRaises(exception.UserParameterMissing,
                          self.resolve,
                          snippet, tmpl, stack)

    def test_resource_refs(self):
        tmpl = parser.Template(resource_template)
        stack = parser.Stack(self.ctx, 'test', tmpl)

        self.m.StubOutWithMock(stack['foo'], 'FnGetRefId')
        stack['foo'].FnGetRefId().MultipleTimes().AndReturn('bar')
        self.m.ReplayAll()

        r_snippet = {"Ref": "foo"}
        self.assertEqual("bar", self.resolve(r_snippet, tmpl, stack))
        self.m.VerifyAll()

    def test_resource_refs_param(self):
        tmpl = parser.Template(resource_template)
        stack = parser.Stack(self.ctx, 'test', tmpl)

        p_snippet = {"Ref": "baz"}
        parsed = tmpl.parse(stack, p_snippet)
        self.assertTrue(isinstance(parsed, heat.engine.cfn.functions.ParamRef))

    def test_select_from_list(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Select": ["1", ["foo", "bar"]]}
        self.assertEqual("bar", self.resolve(data, tmpl))

    def test_select_from_list_integer_index(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Select": [1, ["foo", "bar"]]}
        self.assertEqual("bar", self.resolve(data, tmpl))

    def test_select_from_list_out_of_bound(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Select": ["0", ["foo", "bar"]]}
        self.assertEqual("foo", self.resolve(data, tmpl))
        data = {"Fn::Select": ["1", ["foo", "bar"]]}
        self.assertEqual("bar", self.resolve(data, tmpl))
        data = {"Fn::Select": ["2", ["foo", "bar"]]}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_select_from_dict(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Select": ["red", {"red": "robin", "re": "foo"}]}
        self.assertEqual("robin", self.resolve(data, tmpl))

    def test_select_from_none(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Select": ["red", None]}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_select_from_dict_not_existing(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Select": ["green", {"red": "robin", "re": "foo"}]}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_select_from_serialized_json_map(self):
        tmpl = parser.Template(empty_template)
        js = json.dumps({"red": "robin", "re": "foo"})
        data = {"Fn::Select": ["re", js]}
        self.assertEqual("foo", self.resolve(data, tmpl))

    def test_select_from_serialized_json_list(self):
        tmpl = parser.Template(empty_template)
        js = json.dumps(["foo", "fee", "fum"])
        data = {"Fn::Select": ["0", js]}
        self.assertEqual("foo", self.resolve(data, tmpl))

    def test_select_empty_string(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Select": ["0", '']}
        self.assertEqual("", self.resolve(data, tmpl))
        data = {"Fn::Select": ["1", '']}
        self.assertEqual("", self.resolve(data, tmpl))
        data = {"Fn::Select": ["one", '']}
        self.assertEqual("", self.resolve(data, tmpl))

    def test_join(self):
        tmpl = parser.Template(empty_template)
        join = {"Fn::Join": [" ", ["foo", "bar"]]}
        self.assertEqual("foo bar", self.resolve(join, tmpl))

    def test_split_ok(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Split": [";", "foo; bar; achoo"]}
        self.assertEqual(['foo', ' bar', ' achoo'], self.resolve(data, tmpl))

    def test_split_no_delim_in_str(self):
        tmpl = parser.Template(empty_template)
        data = {"Fn::Split": [";", "foo, bar, achoo"]}
        self.assertEqual(['foo, bar, achoo'], self.resolve(data, tmpl))

    def test_base64(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::Base64": "foobar"}
        # For now, the Base64 function just returns the original text, and
        # does not convert to base64 (see issue #133)
        self.assertEqual("foobar", self.resolve(snippet, tmpl))

    def test_get_azs(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::GetAZs": ""}
        self.assertEqual(["nova"], self.resolve(snippet, tmpl))

    def test_get_azs_with_stack(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::GetAZs": ""}
        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template(empty_template))
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        fc = fakes.FakeClient()
        nova.NovaClientPlugin._create().AndReturn(fc)
        self.m.ReplayAll()
        self.assertEqual(["nova1"], self.resolve(snippet, tmpl, stack))

    def test_replace_string_values(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': 'foo', '%var2%': 'bar'},
            '$var1 is %var2%'
        ]}
        self.assertEqual('foo is bar', self.resolve(snippet, tmpl))

    def test_replace_number_values(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': 1, '%var2%': 2},
            '$var1 is not %var2%'
        ]}
        self.assertEqual('1 is not 2', self.resolve(snippet, tmpl))

        snippet = {"Fn::Replace": [
            {'$var1': 1.3, '%var2%': 2.5},
            '$var1 is not %var2%'
        ]}
        self.assertEqual('1.3 is not 2.5', self.resolve(snippet, tmpl))

    def test_replace_none_values(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': None, '${var2}': None},
            '"$var1" is "${var2}"'
        ]}
        self.assertEqual('"" is ""', self.resolve(snippet, tmpl))

    def test_replace_missing_key(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::Replace": [
            {'$var1': 'foo', 'var2': 'bar'},
            '"$var1" is "${var3}"'
        ]}
        self.assertEqual('"foo" is "${var3}"', self.resolve(snippet, tmpl))

    def test_replace_param_values(self):
        tmpl = parser.Template(parameter_template)
        env = environment.Environment({'foo': 'wibble'})
        stack = parser.Stack(self.ctx, 'test_stack', tmpl, env)
        snippet = {"Fn::Replace": [
            {'$var1': {'Ref': 'foo'}, '%var2%': {'Ref': 'blarg'}},
            '$var1 is %var2%'
        ]}
        self.assertEqual('wibble is quux', self.resolve(snippet, tmpl, stack))

    def test_member_list2map_good(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::MemberListToMap": [
            'Name', 'Value', ['.member.0.Name=metric',
                              '.member.0.Value=cpu',
                              '.member.1.Name=size',
                              '.member.1.Value=56']]}
        self.assertEqual({'metric': 'cpu', 'size': '56'},
                         self.resolve(snippet, tmpl))

    def test_member_list2map_good2(self):
        tmpl = parser.Template(empty_template)
        snippet = {"Fn::MemberListToMap": [
            'Key', 'Value', ['.member.2.Key=metric',
                             '.member.2.Value=cpu',
                             '.member.5.Key=size',
                             '.member.5.Value=56']]}
        self.assertEqual({'metric': 'cpu', 'size': '56'},
                         self.resolve(snippet, tmpl))

    def test_resource_facade(self):
        metadata_snippet = {'Fn::ResourceFacade': 'Metadata'}
        deletion_policy_snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}
        update_policy_snippet = {'Fn::ResourceFacade': 'UpdatePolicy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})

        parent_resource.t = rsrc_defn.ResourceDefinition(
            'parent', 'SomeType',
            deletion_policy=rsrc_defn.ResourceDefinition.RETAIN,
            update_policy={"blarg": "wibble"})

        parent_resource.stack = parser.Stack(self.ctx, 'toplevel_stack',
                                             parser.Template(empty_template))
        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template(empty_template),
                             parent_resource=parent_resource)
        self.assertEqual({"foo": "bar"},
                         self.resolve(metadata_snippet, stack.t, stack))
        self.assertEqual('Retain',
                         self.resolve(deletion_policy_snippet, stack.t, stack))
        self.assertEqual({"blarg": "wibble"},
                         self.resolve(update_policy_snippet, stack.t, stack))

    def test_resource_facade_function(self):
        deletion_policy_snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})
        parent_resource.stack = parser.Stack(self.ctx, 'toplevel_stack',
                                             parser.Template(empty_template))
        del_policy = cfn_funcs.Join(parent_resource.stack,
                                    'Fn::Join', ['eta', ['R', 'in']])
        parent_resource.t = rsrc_defn.ResourceDefinition(
            'parent', 'SomeType',
            deletion_policy=del_policy)

        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template(empty_template),
                             parent_resource=parent_resource)
        self.assertEqual('Retain',
                         self.resolve(deletion_policy_snippet, stack.t, stack))

    def test_resource_facade_invalid_arg(self):
        snippet = {'Fn::ResourceFacade': 'wibble'}
        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template(empty_template))
        error = self.assertRaises(ValueError,
                                  self.resolve,
                                  snippet,
                                  stack.t, stack)
        self.assertIn(snippet.keys()[0], six.text_type(error))

    def test_resource_facade_missing_deletion_policy(self):
        snippet = {'Fn::ResourceFacade': 'DeletionPolicy'}

        parent_resource = DummyClass()
        parent_resource.metadata_set({"foo": "bar"})
        parent_resource.t = rsrc_defn.ResourceDefinition('parent', 'SomeType')

        parent_resource.stack = parser.Stack(self.ctx, 'toplevel_stack',
                                             parser.Template(empty_template))
        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template(empty_template),
                             parent_resource=parent_resource)
        self.assertEqual('Delete', self.resolve(snippet, stack.t, stack))

    def test_prevent_parameters_access(self):
        expected_description = "This can be accessed"
        tmpl = parser.Template({'AWSTemplateFormatVersion': '2010-09-09',
                                'Description': expected_description,
                                'Parameters':
                                {'foo': {'Type': 'String', 'Required': True}}})
        self.assertEqual(expected_description, tmpl['Description'])
        keyError = self.assertRaises(KeyError, tmpl.__getitem__, 'Parameters')
        self.assertIn("can not be accessed directly", six.text_type(keyError))

    def test_parameters_section_not_iterable(self):
        expected_description = "This can be accessed"
        tmpl = parser.Template({'AWSTemplateFormatVersion': '2010-09-09',
                                'Description': expected_description,
                                'Parameters':
                                {'foo': {'Type': 'String', 'Required': True}}})
        self.assertEqual(expected_description, tmpl['Description'])
        self.assertNotIn('Parameters', tmpl.keys())

    def test_add_resource(self):
        cfn_tpl = template_format.parse('''
        AWSTemplateFormatVersion: 2010-09-09
        Resources:
          resource1:
            Type: AWS::EC2::Instance
            Properties:
              property1: value1
            Metadata:
              foo: bar
            DependsOn: dummy
            DeletionPolicy: Retain
            UpdatePolicy:
              foo: bar
        ''')
        source = parser.Template(cfn_tpl)
        empty = parser.Template(copy.deepcopy(empty_template))
        stack = parser.Stack(self.ctx, 'test_stack', source)

        for defn in source.resource_definitions(stack).values():
            empty.add_resource(defn)

        self.assertEqual(cfn_tpl['Resources'], empty.t['Resources'])


class TemplateFnErrorTest(HeatTestCase):
    scenarios = [
        ('select_from_list_not_int',
         dict(expect=TypeError,
              snippet={"Fn::Select": ["one", ["foo", "bar"]]})),
        ('select_from_dict_not_str',
         dict(expect=TypeError,
              snippet={"Fn::Select": ["1", {"red": "robin", "re": "foo"}]})),
        ('select_from_serialized_json_wrong',
         dict(expect=ValueError,
              snippet={"Fn::Select": ["not", "no json"]})),
        ('select_wrong_num_args_1',
         dict(expect=ValueError,
              snippet={"Fn::Select": []})),
        ('select_wrong_num_args_2',
         dict(expect=ValueError,
              snippet={"Fn::Select": ["4"]})),
        ('select_wrong_num_args_3',
         dict(expect=ValueError,
              snippet={"Fn::Select": ["foo", {"foo": "bar"}, ""]})),
        ('select_wrong_num_args_4',
         dict(expect=TypeError,
              snippet={'Fn::Select': [['f'], {'f': 'food'}]})),
        ('split_no_delim',
         dict(expect=ValueError,
              snippet={"Fn::Split": ["foo, bar, achoo"]})),
        ('split_no_list',
         dict(expect=TypeError,
              snippet={"Fn::Split": "foo, bar, achoo"})),
        ('base64_list',
         dict(expect=TypeError,
              snippet={"Fn::Base64": ["foobar"]})),
        ('base64_dict',
         dict(expect=TypeError,
              snippet={"Fn::Base64": {"foo": "bar"}})),
        ('replace_list_value',
         dict(expect=TypeError,
              snippet={"Fn::Replace": [
                  {'$var1': 'foo', '%var2%': ['bar']},
                  '$var1 is %var2%']})),
        ('replace_list_mapping',
         dict(expect=TypeError,
              snippet={"Fn::Replace": [
                  ['var1', 'foo', 'var2', 'bar'],
                  '$var1 is ${var2}']})),
        ('replace_dict',
         dict(expect=TypeError,
              snippet={"Fn::Replace": {}})),
        ('replace_missing_template',
         dict(expect=ValueError,
              snippet={"Fn::Replace": [['var1', 'foo', 'var2', 'bar']]})),
        ('replace_none_template',
         dict(expect=TypeError,
              snippet={"Fn::Replace": [['var2', 'bar'], None]})),
        ('replace_list_string',
         dict(expect=TypeError,
              snippet={"Fn::Replace": [
                  {'var1': 'foo', 'var2': 'bar'},
                  ['$var1 is ${var2}']]})),
        ('join_string',
         dict(expect=TypeError,
              snippet={"Fn::Join": [" ", "foo"]})),
        ('join_dict',
         dict(expect=TypeError,
              snippet={"Fn::Join": [" ", {"foo": "bar"}]})),
        ('join_wrong_num_args_1',
         dict(expect=ValueError,
              snippet={"Fn::Join": []})),
        ('join_wrong_num_args_2',
         dict(expect=ValueError,
              snippet={"Fn::Join": [" "]})),
        ('join_wrong_num_args_3',
         dict(expect=ValueError,
              snippet={"Fn::Join": [" ", {"foo": "bar"}, ""]})),
        ('join_string_nodelim',
         dict(expect=TypeError,
              snippet={"Fn::Join": "o"})),
        ('join_string_nodelim_1',
         dict(expect=TypeError,
              snippet={"Fn::Join": "oh"})),
        ('join_string_nodelim_2',
         dict(expect=TypeError,
              snippet={"Fn::Join": "ohh"})),
        ('join_dict_nodelim1',
         dict(expect=TypeError,
              snippet={"Fn::Join": {"foo": "bar"}})),
        ('join_dict_nodelim2',
         dict(expect=TypeError,
              snippet={"Fn::Join": {"foo": "bar", "blarg": "wibble"}})),
        ('join_dict_nodelim3',
         dict(expect=TypeError,
              snippet={"Fn::Join": {"foo": "bar", "blarg": "wibble",
                                    "baz": "quux"}})),
        ('member_list2map_no_key_or_val',
         dict(expect=TypeError,
              snippet={"Fn::MemberListToMap": [
                  'Key', ['.member.2.Key=metric',
                          '.member.2.Value=cpu',
                          '.member.5.Key=size',
                          '.member.5.Value=56']]})),
        ('member_list2map_no_list',
         dict(expect=TypeError,
              snippet={"Fn::MemberListToMap": [
                  'Key', '.member.2.Key=metric']})),
        ('member_list2map_not_string',
         dict(expect=TypeError,
              snippet={"Fn::MemberListToMap": [
                  'Name', ['Value'], ['.member.0.Name=metric',
                                      '.member.0.Value=cpu',
                                      '.member.1.Name=size',
                                      '.member.1.Value=56']]})),
    ]

    def test_bad_input(self):
        tmpl = parser.Template(empty_template)
        resolve = lambda s: TemplateTest.resolve(s, tmpl)
        error = self.assertRaises(self.expect,
                                  resolve,
                                  self.snippet)
        self.assertIn(self.snippet.keys()[0], six.text_type(error))


class ResolveDataTest(HeatTestCase):

    def setUp(self):
        super(ResolveDataTest, self).setUp()
        self.username = 'parser_stack_test_user'

        self.ctx = utils.dummy_context()

        self.stack = parser.Stack(self.ctx, 'resolve_test_stack',
                                  template.Template(empty_template),
                                  environment.Environment({}))

    def resolve(self, snippet):
        return function.resolve(self.stack.t.parse(self.stack, snippet))

    def test_stack_resolve_runtime_data_deprecated(self):
        stack = parser.Stack(self.ctx, 'test_stack',
                             parser.Template(empty_template),
                             tenant_id='bar')

        with warnings.catch_warnings(record=True) as ws:
            warnings.filterwarnings('always')

            # Work around http://bugs.python.org/issue4180
            getattr(parser, '__warningregistry__', {}).clear()

            test_data = {'foo': 'bar'}
            resolved = stack.resolve_runtime_data(test_data)

            self.assertTrue(ws)
            self.assertTrue(issubclass(ws[0].category, DeprecationWarning))

            self.assertEqual(test_data, resolved)

    def test_join_split(self):
        # join
        snippet = {'Fn::Join': [';', ['one', 'two', 'three']]}
        self.assertEqual('one;two;three',
                         self.resolve(snippet))

        # join then split
        snippet = {'Fn::Split': [';', snippet]}
        self.assertEqual(['one', 'two', 'three'],
                         self.resolve(snippet))

    def test_split_join_split_join(self):
        # each snippet in this test encapsulates
        # the snippet from the previous step, leading
        # to increasingly nested function calls

        # split
        snippet = {'Fn::Split': [',', 'one,two,three']}
        self.assertEqual(['one', 'two', 'three'],
                         self.resolve(snippet))

        # split then join
        snippet = {'Fn::Join': [';', snippet]}
        self.assertEqual('one;two;three',
                         self.resolve(snippet))

        # split then join then split
        snippet = {'Fn::Split': [';', snippet]}
        self.assertEqual(['one', 'two', 'three'],
                         self.resolve(snippet))

        # split then join then split then join
        snippet = {'Fn::Join': ['-', snippet]}
        self.assertEqual('one-two-three',
                         self.resolve(snippet))

    def test_join_recursive(self):
        raw = {'Fn::Join': ['\n', [{'Fn::Join':
                                   [' ', ['foo', 'bar']]}, 'baz']]}
        self.assertEqual('foo bar\nbaz', self.resolve(raw))

    def test_join_not_string(self):
        snippet = {'Fn::Join': ['\n', [{'Fn::Join':
                                        [' ', ['foo', 45]]}, 'baz']]}
        error = self.assertRaises(TypeError,
                                  self.resolve,
                                  snippet)
        self.assertIn('45', six.text_type(error))

    def test_base64_replace(self):
        raw = {'Fn::Base64': {'Fn::Replace': [
            {'foo': 'bar'}, 'Meet at the foo']}}
        self.assertEqual('Meet at the bar',
                         self.resolve(raw))

    def test_replace_base64(self):
        raw = {'Fn::Replace': [{'foo': 'bar'}, {
            'Fn::Base64': 'Meet at the foo'}]}
        self.assertEqual('Meet at the bar',
                         self.resolve(raw))

    def test_nested_selects(self):
        data = {
            'a': ['one', 'two', 'three'],
            'b': ['een', 'twee', {'d': 'D', 'e': 'E'}]
        }
        raw = {'Fn::Select': ['a', data]}
        self.assertEqual(data['a'],
                         self.resolve(raw))

        raw = {'Fn::Select': ['b', data]}
        self.assertEqual(data['b'],
                         self.resolve(raw))

        raw = {
            'Fn::Select': ['1', {
                'Fn::Select': ['b', data]}]}
        self.assertEqual('twee',
                         self.resolve(raw))

        raw = {
            'Fn::Select': ['e', {
                'Fn::Select': ['2', {
                    'Fn::Select': ['b', data]}]}]}
        self.assertEqual('E',
                         self.resolve(raw))

    def test_member_list_select(self):
        snippet = {'Fn::Select': ['metric', {"Fn::MemberListToMap": [
            'Name', 'Value', ['.member.0.Name=metric',
                              '.member.0.Value=cpu',
                              '.member.1.Name=size',
                              '.member.1.Value=56']]}]}
        self.assertEqual('cpu',
                         self.resolve(snippet))


class StackTest(HeatTestCase):
    def setUp(self):
        super(StackTest, self).setUp()

        self.username = 'parser_stack_test_user'
        self.tmpl = parser.Template(copy.deepcopy(empty_template))

        self.ctx = utils.dummy_context()

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithPropsType',
                                 generic_rsrc.ResourceWithProps)
        resource._register_class('ResourceWithComplexAttributesType',
                                 generic_rsrc.ResourceWithComplexAttributes)
        resource._register_class('ResWithComplexPropsAndAttrs',
                                 generic_rsrc.ResWithComplexPropsAndAttrs)

    def test_stack_reads_tenant(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             tenant_id='bar')
        self.assertEqual('bar', stack.tenant_id)

    def test_stack_reads_tenant_from_context_if_empty(self):
        self.ctx.tenant_id = 'foo'
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             tenant_id=None)
        self.assertEqual('foo', stack.tenant_id)

    def test_stack_reads_username(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             username='bar')
        self.assertEqual('bar', stack.username)

    def test_stack_reads_username_from_context_if_empty(self):
        self.ctx.username = 'foo'
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             username=None)
        self.assertEqual('foo', stack.username)

    def test_stack_string_repr(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl)
        expected = 'Stack "%s" [%s]' % (stack.name, stack.id)
        observed = str(stack)
        self.assertEqual(expected, observed)

    def test_state_defaults(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl)
        self.assertEqual(('CREATE', 'IN_PROGRESS'), stack.state)
        self.assertEqual('', stack.status_reason)

    def test_timeout_secs_default(self):
        cfg.CONF.set_override('stack_action_timeout', 1000)
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl)
        self.assertIsNone(stack.timeout_mins)
        self.assertEqual(1000, stack.timeout_secs())

    def test_timeout_secs(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             timeout_mins=10)
        self.assertEqual(600, stack.timeout_secs())

    def test_no_auth_token(self):
        ctx = utils.dummy_context()
        ctx.auth_token = None
        self.stub_keystoneclient()

        self.m.ReplayAll()
        stack = parser.Stack(ctx, 'test_stack', self.tmpl)
        self.assertEqual('abcd1234',
                         stack.clients.client('keystone').auth_token)

        self.m.VerifyAll()

    def test_state(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             action=parser.Stack.CREATE,
                             status=parser.Stack.IN_PROGRESS)
        self.assertEqual((parser.Stack.CREATE, parser.Stack.IN_PROGRESS),
                         stack.state)
        stack.state_set(parser.Stack.CREATE, parser.Stack.COMPLETE, 'test')
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         stack.state)
        stack.state_set(parser.Stack.DELETE, parser.Stack.COMPLETE, 'test')
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         stack.state)

    def test_state_deleted(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             action=parser.Stack.CREATE,
                             status=parser.Stack.IN_PROGRESS)
        stack.id = '1234'

        # Simulate a deleted stack
        self.m.StubOutWithMock(db_api, 'stack_get')
        db_api.stack_get(stack.context, stack.id).AndReturn(None)

        self.m.ReplayAll()

        self.assertIsNone(stack.state_set(parser.Stack.CREATE,
                                          parser.Stack.COMPLETE, 'test'))
        self.m.VerifyAll()

    def test_state_bad(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             action=parser.Stack.CREATE,
                             status=parser.Stack.IN_PROGRESS)
        self.assertEqual((parser.Stack.CREATE, parser.Stack.IN_PROGRESS),
                         stack.state)
        self.assertRaises(ValueError, stack.state_set,
                          'baad', parser.Stack.COMPLETE, 'test')
        self.assertRaises(ValueError, stack.state_set,
                          parser.Stack.CREATE, 'oops', 'test')

    def test_status_reason(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             status_reason='quux')
        self.assertEqual('quux', stack.status_reason)
        stack.state_set(parser.Stack.CREATE, parser.Stack.IN_PROGRESS,
                        'wibble')
        self.assertEqual('wibble', stack.status_reason)

    def test_load_nonexistant_id(self):
        self.assertRaises(exception.NotFound, parser.Stack.load,
                          None, -1)

    def test_total_resources_empty(self):
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl,
                             status_reason='flimflam')
        self.assertEqual(0, stack.total_resources())

    def test_total_resources_generic(self):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
               {'A': {'Type': 'GenericResourceType'}}}
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template(tpl),
                             status_reason='blarg')
        self.assertEqual(1, stack.total_resources())

    def _setup_nested(self, name):
        nested_tpl = ('{"HeatTemplateFormatVersion" : "2012-12-12",'
                      '"Resources":{'
                      '"A": {"Type": "GenericResourceType"},'
                      '"B": {"Type": "GenericResourceType"}}}')
        tpl = {'HeatTemplateFormatVersion': "2012-12-12",
               'Resources':
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

    def test_total_resources_nested(self):
        self._setup_nested('zyzzyx')
        self.assertEqual(4, self.stack.total_resources())
        self.assertIsNotNone(self.stack['A'].nested())
        self.assertEqual(
            2, self.stack['A'].nested().total_resources())
        self.assertEqual(
            4,
            self.stack['A'].nested().root_stack.total_resources())

    def test_iter_resources(self):
        self._setup_nested('iter_resources')
        nested_stack = self.stack['A'].nested()
        resource_generator = self.stack.iter_resources()
        self.assertIsNot(resource_generator, list)

        first_level_resources = list(resource_generator)
        self.assertEqual(2, len(first_level_resources))
        self.assertIn(self.stack['A'], first_level_resources)
        self.assertIn(self.stack['B'], first_level_resources)

        all_resources = list(self.stack.iter_resources(1))
        self.assertIn(self.stack['A'], first_level_resources)
        self.assertIn(self.stack['B'], first_level_resources)
        self.assertIn(nested_stack['A'], all_resources)
        self.assertIn(nested_stack['B'], all_resources)

    def test_root_stack(self):
        self._setup_nested('toor')
        self.assertEqual(self.stack, self.stack.root_stack)
        self.assertIsNotNone(self.stack['A'].nested())
        self.assertEqual(
            self.stack, self.stack['A'].nested().root_stack)

    def test_nested_stack_abandon(self):
        self._setup_nested('nestedstack')
        ret = self.stack.prepare_abandon()
        self.assertIsNotNone(self.stack['A'].nested())
        self.assertEqual(
            self.stack, self.stack['A'].nested().root_stack)

        keys = ['name', 'id', 'action', 'status', 'template', 'resources',
                'project_id', 'stack_user_project_id', 'environment']

        self.assertEqual(len(keys), len(ret))
        nested_stack_data = ret['resources']['A']
        self.assertEqual(len(keys), len(nested_stack_data))
        for key in keys:
            self.assertIn(key, ret)
            self.assertIn(key, nested_stack_data)

    def test_load_parent_resource(self):
        self.stack = parser.Stack(self.ctx, 'load_parent_resource',
                                  self.tmpl)
        self.stack.store()
        stack = db_api.stack_get(self.ctx, self.stack.id)

        t = template.Template.load(self.ctx, stack.raw_template_id)
        self.m.StubOutWithMock(template.Template, 'load')
        template.Template.load(
            self.ctx, stack.raw_template_id, stack.raw_template
        ).AndReturn(t)

        env = environment.Environment(stack.parameters)
        self.m.StubOutWithMock(environment, 'Environment')
        environment.Environment(stack.parameters).AndReturn(env)

        self.m.StubOutWithMock(parser.Stack, '__init__')
        parser.Stack.__init__(self.ctx, stack.name, t, env, stack.id,
                              stack.action, stack.status, stack.status_reason,
                              stack.timeout, True, stack.disable_rollback,
                              'parent', owner_id=None,
                              stack_user_project_id=None,
                              created_time=IgnoreArg(),
                              updated_time=None,
                              user_creds_id=stack.user_creds_id,
                              tenant_id='test_tenant_id',
                              use_stored_context=False,
                              username=IgnoreArg())

        self.m.ReplayAll()
        parser.Stack.load(self.ctx, stack_id=self.stack.id,
                          parent_resource='parent')

        self.m.VerifyAll()

    def test_identifier(self):
        self.stack = parser.Stack(self.ctx, 'identifier_test',
                                  self.tmpl)
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
        self.stack = parser.Stack(self.ctx, 'stack_details_test',
                                  parser.Template(tpl),
                                  tenant_id='123',
                                  stack_user_project_id='234',
                                  env=env)
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
        self.stack = parser.Stack(self.ctx, 'param_arn_test',
                                  self.tmpl)
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

    def test_set_param_id_update(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Metadata': {'Bar': {'Ref': 'AWS::StackId'}},
                              'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_stack_arn_test',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        stack_arn = self.stack.parameters['AWS::StackId']

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'ResourceWithPropsType',
                               'Metadata': {'Bar': {'Ref': 'AWS::StackId'}},
                               'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])

        self.assertEqual(
            stack_arn, self.stack['AResource'].metadata_get()['Bar'])

    def test_load_param_id(self):
        self.stack = parser.Stack(self.ctx, 'param_load_arn_test',
                                  self.tmpl)
        self.stack.store()
        identifier = self.stack.identifier()
        self.assertEqual(self.stack.parameters['AWS::StackId'],
                         identifier.arn())

        newstack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
        self.assertEqual(identifier.arn(), newstack.parameters['AWS::StackId'])

    def test_load_reads_tenant_id(self):
        self.ctx.tenant_id = 'foobar'
        self.stack = parser.Stack(self.ctx, 'stack_name', self.tmpl)
        self.stack.store()
        stack_id = self.stack.id
        self.ctx.tenant_id = None
        stack = parser.Stack.load(self.ctx, stack_id=stack_id)
        self.assertEqual('foobar', stack.tenant_id)

    def test_load_reads_username_from_db(self):
        self.ctx.username = 'foobar'
        self.stack = parser.Stack(self.ctx, 'stack_name', self.tmpl)
        self.stack.store()
        stack_id = self.stack.id

        self.ctx.username = None
        stack = parser.Stack.load(self.ctx, stack_id=stack_id)
        self.assertEqual('foobar', stack.username)

        self.ctx.username = 'not foobar'
        stack = parser.Stack.load(self.ctx, stack_id=stack_id)
        self.assertEqual('foobar', stack.username)

    def test_load_all(self):
        stack1 = parser.Stack(self.ctx, 'stack1', self.tmpl)
        stack1.store()
        stack2 = parser.Stack(self.ctx, 'stack2', self.tmpl)
        stack2.store()

        stacks = list(parser.Stack.load_all(self.ctx))
        self.assertEqual(2, len(stacks))

        # Add another, nested, stack
        stack3 = parser.Stack(self.ctx, 'stack3', self.tmpl,
                              owner_id=stack2.id)
        stack3.store()

        # Should still be 2 without show_nested
        stacks = list(parser.Stack.load_all(self.ctx))
        self.assertEqual(2, len(stacks))

        stacks = list(parser.Stack.load_all(self.ctx, show_nested=True))
        self.assertEqual(3, len(stacks))

        # A backup stack should not be returned
        stack1._backup_stack()
        stacks = list(parser.Stack.load_all(self.ctx))
        self.assertEqual(2, len(stacks))

        stacks = list(parser.Stack.load_all(self.ctx, show_nested=True))
        self.assertEqual(3, len(stacks))

    def test_created_time(self):
        self.stack = parser.Stack(self.ctx, 'creation_time_test',
                                  self.tmpl)
        self.assertIsNone(self.stack.created_time)
        self.stack.store()
        self.assertIsNotNone(self.stack.created_time)

    def test_updated_time(self):
        self.stack = parser.Stack(self.ctx, 'updated_time_test',
                                  self.tmpl)
        self.assertIsNone(self.stack.updated_time)
        self.stack.store()
        self.stack.create()

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'R1': {'Type': 'GenericResourceType'}}}
        newstack = parser.Stack(self.ctx, 'updated_time_test',
                                parser.Template(tmpl))
        self.stack.update(newstack)
        self.assertIsNotNone(self.stack.updated_time)

    def test_access_policy_update(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'R1': {'Type': 'GenericResourceType'},
                'Policy': {
                    'Type': 'OS::Heat::AccessPolicy',
                    'Properties': {
                        'AllowedResources': ['R1'],
                    },
                }}}

        self.stack = parser.Stack(self.ctx, 'update_stack_access_policy_test',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'R1': {'Type': 'GenericResourceType'},
                 'R2': {'Type': 'GenericResourceType'},
                 'Policy': {
                     'Type': 'OS::Heat::AccessPolicy',
                     'Properties': {
                         'AllowedResources': ['R1', 'R2'],
                     },
                 }}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)

    def test_delete(self):
        self.stack = parser.Stack(self.ctx, 'delete_test',
                                  self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_user_creds(self):
        self.stack = parser.Stack(self.ctx, 'delete_test',
                                  self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertIsNotNone(db_s.user_creds_id)
        user_creds_id = db_s.user_creds_id
        db_creds = db_api.user_creds_get(db_s.user_creds_id)
        self.assertIsNotNone(db_creds)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        db_creds = db_api.user_creds_get(user_creds_id)
        self.assertIsNone(db_creds)
        del_db_s = db_api.stack_get(self.ctx, stack_id, show_deleted=True)
        self.assertIsNone(del_db_s.user_creds_id)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_user_creds_gone_missing(self):
        '''It may happen that user_creds were deleted when a delete
           operation was stopped. We should be resilient to this and still
           complete the delete operation.
           '''
        self.stack = parser.Stack(self.ctx, 'delete_test',
                                  self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertIsNotNone(db_s.user_creds_id)
        user_creds_id = db_s.user_creds_id
        db_creds = db_api.user_creds_get(db_s.user_creds_id)
        self.assertIsNotNone(db_creds)

        db_api.user_creds_delete(self.ctx, user_creds_id)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        db_creds = db_api.user_creds_get(user_creds_id)
        self.assertIsNone(db_creds)
        del_db_s = db_api.stack_get(self.ctx, stack_id, show_deleted=True)
        self.assertIsNone(del_db_s.user_creds_id)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_trust(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')
        self.stub_keystoneclient()

        self.stack = parser.Stack(
            self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_trust_trustor(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        trustor_ctx = utils.dummy_context(user_id='thetrustor')
        self.m.StubOutWithMock(hkc, 'KeystoneClient')
        hkc.KeystoneClient(trustor_ctx).AndReturn(
            FakeKeystoneClient(user_id='thetrustor'))
        self.m.ReplayAll()

        self.stack = parser.Stack(
            trustor_ctx, 'delete_trust_nt', self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        user_creds_id = db_s.user_creds_id
        self.assertIsNotNone(user_creds_id)
        user_creds = db_api.user_creds_get(user_creds_id)
        self.assertEqual('thetrustor', user_creds.get('trustor_user_id'))

        self.stack.delete()

        db_s = db_api.stack_get(trustor_ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_trust_not_trustor(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        # Stack gets created with trustor_ctx, deleted with other_ctx
        # then the trust delete should be with stored_ctx
        trustor_ctx = utils.dummy_context(user_id='thetrustor')
        other_ctx = utils.dummy_context(user_id='nottrustor')
        stored_ctx = utils.dummy_context(trust_id='thetrust')

        self.m.StubOutWithMock(hkc, 'KeystoneClient')
        hkc.KeystoneClient(trustor_ctx).AndReturn(
            FakeKeystoneClient(user_id='thetrustor'))
        self.m.StubOutWithMock(parser.Stack, 'stored_context')
        parser.Stack.stored_context().AndReturn(stored_ctx)
        hkc.KeystoneClient(stored_ctx).AndReturn(
            FakeKeystoneClient(user_id='nottrustor'))
        self.m.ReplayAll()

        self.stack = parser.Stack(
            trustor_ctx, 'delete_trust_nt', self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        user_creds_id = db_s.user_creds_id
        self.assertIsNotNone(user_creds_id)
        user_creds = db_api.user_creds_get(user_creds_id)
        self.assertEqual('thetrustor', user_creds.get('trustor_user_id'))

        loaded_stack = parser.Stack.load(other_ctx, self.stack.id)
        loaded_stack.delete()

        db_s = db_api.stack_get(other_ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         loaded_stack.state)

    def test_delete_trust_backup(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        class FakeKeystoneClientFail(FakeKeystoneClient):
            def delete_trust(self, trust_id):
                raise Exception("Shouldn't delete")

        self.m.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
        keystone.KeystoneClientPlugin._create().AndReturn(
            FakeKeystoneClientFail())
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(backup=True)

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual(self.stack.state,
                         (parser.Stack.DELETE, parser.Stack.COMPLETE))

    def test_delete_trust_nested(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        class FakeKeystoneClientFail(FakeKeystoneClient):
            def delete_trust(self, trust_id):
                raise Exception("Shouldn't delete")

        self.stub_keystoneclient(fake_client=FakeKeystoneClientFail())

        self.stack = parser.Stack(
            self.ctx, 'delete_trust_nested', self.tmpl,
            owner_id='owner123')
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        user_creds_id = db_s.user_creds_id
        self.assertIsNotNone(user_creds_id)
        user_creds = db_api.user_creds_get(user_creds_id)
        self.assertIsNotNone(user_creds)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        user_creds = db_api.user_creds_get(user_creds_id)
        self.assertIsNotNone(user_creds)
        self.assertEqual(self.stack.state,
                         (parser.Stack.DELETE, parser.Stack.COMPLETE))

    def test_delete_trust_fail(self):
        cfg.CONF.set_override('deferred_auth_method', 'trusts')

        class FakeKeystoneClientFail(FakeKeystoneClient):
            def delete_trust(self, trust_id):
                raise kc_exceptions.Forbidden("Denied!")

        self.m.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
        keystone.KeystoneClientPlugin._create().AndReturn(
            FakeKeystoneClientFail())
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.FAILED),
                         self.stack.state)
        self.assertIn('Error deleting trust', self.stack.status_reason)

    def test_delete_deletes_project(self):
        fkc = FakeKeystoneClient()
        fkc.delete_stack_domain_project = mock.Mock()

        self.m.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
        keystone.KeystoneClientPlugin._create().AndReturn(fkc)
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        self.stack.set_stack_user_project_id(project_id='aproject456')

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        fkc.delete_stack_domain_project.assert_called_once_with(
            project_id='aproject456')

    def test_abandon_nodelete_project(self):
        fkc = FakeKeystoneClient()
        fkc.delete_stack_domain_project = mock.Mock()

        self.m.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
        keystone.KeystoneClientPlugin._create().AndReturn(fkc)
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        self.stack.set_stack_user_project_id(project_id='aproject456')

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(abandon=True)

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertFalse(fkc.delete_stack_domain_project.called)

    def test_suspend_resume(self):
        self.m.ReplayAll()
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = parser.Stack(self.ctx, 'suspend_test',
                                  parser.Template(tmpl))
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

        self.m.VerifyAll()

    def test_suspend_stack_suspended_ok(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = parser.Stack(self.ctx, 'suspend_test',
                                  parser.Template(tmpl))
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
        self.stack = parser.Stack(self.ctx, 'suspend_test',
                                  parser.Template(tmpl))
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

        self.stack = parser.Stack(self.ctx, 'suspend_test_fail',
                                  parser.Template(tmpl))

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

        self.stack = parser.Stack(self.ctx, 'resume_test_fail',
                                  parser.Template(tmpl))

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

        self.stack = parser.Stack(self.ctx, 'suspend_test_fail_timeout',
                                  parser.Template(tmpl))

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

        self.stack = parser.Stack(self.ctx, 'resume_test_fail_timeout',
                                  parser.Template(tmpl))

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
        def _mock_check(res):
            res.handle_check = mock.Mock()
            if hasattr(res, 'nested'):
                [_mock_check(r) for r in res.nested().resources.values()]

        self._setup_nested(name)
        [_mock_check(res) for res in self.stack.resources.values()]
        return self.stack

    def test_check_supported(self):
        stack = self._get_stack_to_check('check-supported')
        stack.check()

        self.assertEqual(stack.COMPLETE, stack.status)
        self.assertEqual(stack.CHECK, stack.action)
        [self.assertTrue(res.handle_check.called)
         for res in stack.resources.values()]
        self.assertNotIn('not fully supported', stack.status_reason)

    def test_check_nested_stack(self):
        def _mock_check(res):
            res.handle_check = mock.Mock()

        self._setup_nested('check-nested-stack')
        nested = self.stack['A'].nested()
        [_mock_check(res) for res in nested.resources.values()]
        self.stack.check()

        [self.assertTrue(res.handle_check.called)
         for res in nested.resources.values()]

    def test_check_not_supported(self):
        stack = self._get_stack_to_check('check-not-supported')
        del stack['B'].handle_check
        stack.check()

        self.assertEqual(stack.COMPLETE, stack.status)
        self.assertEqual(stack.CHECK, stack.action)
        self.assertTrue(stack['A'].handle_check.called)
        self.assertIn('not fully supported', stack.status_reason)

    def test_check_fail(self):
        stack = self._get_stack_to_check('check-fail')
        stack['A'].handle_check.side_effect = Exception('fail-A')
        stack['B'].handle_check.side_effect = Exception('fail-B')
        stack.check()

        self.assertEqual(stack.FAILED, stack.status)
        self.assertEqual(stack.CHECK, stack.action)
        self.assertTrue(stack['A'].handle_check.called)
        self.assertTrue(stack['B'].handle_check.called)
        self.assertIn('fail-A', stack.status_reason)
        self.assertIn('fail-B', stack.status_reason)

    def test_delete_rollback(self):
        self.stack = parser.Stack(self.ctx, 'delete_rollback_test',
                                  self.tmpl, disable_rollback=False)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(action=self.stack.ROLLBACK)

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_badaction(self):
        self.stack = parser.Stack(self.ctx, 'delete_badaction_test',
                                  self.tmpl)
        stack_id = self.stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(action="wibble")

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertEqual((parser.Stack.DELETE, parser.Stack.FAILED),
                         self.stack.state)

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

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
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

        loaded_stack = parser.Stack.load(self.ctx, self.stack.id)
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
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
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
        self.stack = parser.Stack(utils.dummy_context(),
                                  'test_stack',
                                  tmpl,
                                  disable_rollback=False,
                                  adopt_stack_data=json.loads(adopt_data))
        self.stack.store()
        self.stack.adopt()
        self.assertEqual((self.stack.ROLLBACK, self.stack.COMPLETE),
                         self.stack.state)

    def test_resource_by_refid(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'resource_by_refid_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
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

    def test_update_add(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

    def test_update_remove(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'GenericResourceType'},
                'BResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertNotIn('BResource', self.stack)

    def test_update_description(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Description': 'BTemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('BTemplate',
                         self.stack.t[self.stack.t.DESCRIPTION])

    def test_update_timeout(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl), timeout_mins=60)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Description': 'ATemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2), timeout_mins=30)
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(30, self.stack.timeout_mins)

    def test_update_disable_rollback(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Description': 'ATemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(True, self.stack.disable_rollback)

    def test_update_modify_ok_replace(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])

        loaded_stack = parser.Stack.load(self.ctx, self.stack.id)
        stored_props = loaded_stack['AResource']._stored_properties_data
        self.assertEqual({'Foo': 'xyz'}, stored_props)

        self.m.VerifyAll()

    def test_update_modify_ok_replace_int(self):
        # create
        #========
        tmpl = {'heat_template_version': '2013-05-23',
                'resources': {'AResource': {
                    'type': 'ResWithComplexPropsAndAttrs',
                    'properties': {'an_int': 1}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        stack_id = self.stack.id
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        value1 = 2
        prop_diff1 = {'an_int': value1}
        value2 = 1
        prop_diff2 = {'an_int': value2}

        self.m.StubOutWithMock(generic_rsrc.ResWithComplexPropsAndAttrs,
                               'handle_update')
        generic_rsrc.ResWithComplexPropsAndAttrs.handle_update(
            IgnoreArg(), IgnoreArg(), prop_diff1)
        generic_rsrc.ResWithComplexPropsAndAttrs.handle_update(
            IgnoreArg(), IgnoreArg(), prop_diff2)

        self.m.ReplayAll()

        # update 1
        #==========

        self.stack = parser.Stack.load(self.ctx, stack_id=stack_id)
        tmpl2 = {'heat_template_version': '2013-05-23',
                 'resources': {'AResource': {
                     'type': 'ResWithComplexPropsAndAttrs',
                     'properties': {'an_int': value1}}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)

        # update 2
        #==========
        # reload the previous stack
        self.stack = parser.Stack.load(self.ctx, stack_id=stack_id)
        tmpl3 = {'heat_template_version': '2013-05-23',
                 'resources': {'AResource': {
                     'type': 'ResWithComplexPropsAndAttrs',
                     'properties': {'an_int': value2}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl3))

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)

        self.m.VerifyAll()

    def test_update_modify_param_ok_replace(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'foo': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {'Foo': {'Ref': 'foo'}}
                }
            }
        }

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps,
                               'update_template_diff')

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  environment.Environment({'foo': 'abc'}))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl),
                                     environment.Environment({'foo': 'xyz'}))

        def check_props(*args):
            self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        generic_rsrc.ResourceWithProps.update_template_diff(
            {'Type': 'ResourceWithPropsType',
             'Properties': {'Foo': 'xyz'}},
            {'Type': 'ResourceWithPropsType',
             'Properties': {'Foo': 'abc'}}).WithSideEffects(check_props) \
                                           .AndRaise(resource.UpdateReplace)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])
        self.m.VerifyAll()

    def test_update_modify_update_failed(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        res = self.stack['AResource']
        res.update_allowed_properties = ('Foo',)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
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
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_failed_delete(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # make the update fail deleting the existing resource
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()
        # Unset here so destroy() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    def test_update_modify_replace_failed_create(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_failed_create_and_delete_1(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'b_res'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_failed_create_and_delete_2(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'c_res'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create()
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'c_res').AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        # set resource_id for AResource because handle_create() is overwritten
        # by the mox.
        self.stack.resources['AResource'].resource_id_set('c_res')
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_create_in_progress_and_delete_1(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'b_res'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        # Override stack status and resources status for emulating
        # IN_PROGRESS situation
        self.stack.state_set(
            parser.Stack.UPDATE, parser.Stack.IN_PROGRESS, None)
        self.stack.resources['AResource'].state_set(
            resource.Resource.CREATE, resource.Resource.IN_PROGRESS, None)
        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_create_in_progress_and_delete_2(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'c_res'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create()
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'c_res').AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        # set resource_id for AResource because handle_create() is overwritten
        # by the mox.
        self.stack.resources['AResource'].resource_id_set('c_res')
        # Override stack status and resources status for emulating
        # IN_PROGRESS situation
        self.stack.state_set(
            parser.Stack.UPDATE, parser.Stack.IN_PROGRESS, None)
        self.stack.resources['BResource'].state_set(
            resource.Resource.CREATE, resource.Resource.IN_PROGRESS, None)
        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_add_signal(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        updater = scheduler.TaskRunner(self.stack.update_task, updated_stack)
        updater.start()
        while 'BResource' not in self.stack:
            self.assertFalse(updater.step())
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.IN_PROGRESS),
                         self.stack.state)

        # Reload the stack from the DB and prove that it contains the new
        # resource already
        re_stack = parser.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)

        updater.run_to_completion()
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

    def test_update_add_failed_create(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        # patch in a dummy handle_create making BResource fail creating
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = parser.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)
        self.m.VerifyAll()

    def test_update_add_failed_create_rollback_failed(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)

        # patch in a dummy handle_create making BResource fail creating
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_delete')
        generic_rsrc.GenericResource.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.FAILED),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = parser.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)
        self.m.VerifyAll()

    def test_update_rollback(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        with mock.patch.object(self.stack, 'state_set',
                               side_effect=self.stack.state_set) as mock_state:
            self.stack.update(updated_stack)
            self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                             self.stack.state)
            self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
            self.assertEqual(2, mock_state.call_count)
            self.assertEqual(('UPDATE', 'IN_PROGRESS'),
                             mock_state.call_args_list[0][0][:2])
            self.assertEqual(('ROLLBACK', 'IN_PROGRESS'),
                             mock_state.call_args_list[1][0][:2])
        self.m.VerifyAll()

    def test_update_rollback_on_cancel_event(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}},
                               }}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)
        evt_mock = mock.MagicMock()
        evt_mock.ready.return_value = True
        evt_mock.wait.return_value = 'cancel'

        self.m.ReplayAll()

        self.stack.update(updated_stack, event=evt_mock)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.m.VerifyAll()

    def test_update_rollback_fail(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Parameters': {'AParam': {'Type': 'String'}},
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        env1 = {'parameters': {'AParam': 'abc'}}
        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False,
                                  env=environment.Environment(env1))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Parameters': {'BParam': {'Type': 'String'}},
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        env2 = {'parameters': {'BParam': 'smelly'}}
        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False,
                                     env=environment.Environment(env2))

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc, and again on the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_rollback_add(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'GenericResourceType'},
                 'BResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc, and succeed on the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertNotIn('BResource', self.stack)
        self.m.VerifyAll()

    def test_update_rollback_remove(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'GenericResourceType'},
                'BResource': {'Type': 'ResourceWithPropsType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)

        # patch in a dummy delete making the destroy fail
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        # replace the failed resource on rollback
        generic_rsrc.ResourceWithProps.handle_create()
        generic_rsrc.ResourceWithProps.handle_delete()
        self.m.ReplayAll()

        self.stack.update(updated_stack)

        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)
        self.m.VerifyAll()
        # Unset here so delete() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    def test_update_rollback_replace(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'foo'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'bar'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)

        # patch in a dummy delete making the destroy fail
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()
        # Unset here so delete() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    def test_update_replace_by_reference(self):
        '''
        assertion:
        changes in dynamic attributes, due to other resources been updated
        are not ignored and can cause dependent resources to be updated.
        '''
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {
                                  'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                                   'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'FnGetRefId')
        generic_rsrc.ResourceWithProps.FnGetRefId().AndReturn(
            'AResource')
        generic_rsrc.ResourceWithProps.FnGetRefId().MultipleTimes().AndReturn(
            'inst-007')
        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('inst-007', self.stack['BResource'].properties['Foo'])
        self.m.VerifyAll()

    def test_update_with_new_resources_with_reference(self):
        '''
        assertion:
        check, that during update with new resources which one has
        reference on second, reference will be correct resolved.
        '''
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'CResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'abc'}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'CResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {'Foo': 'abc'}},
                 'AResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                                   'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['CResource'].properties['Foo'])
        self.assertEqual(1, len(self.stack.resources))

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        generic_rsrc.ResourceWithProps.handle_create().MultipleTimes().\
            AndReturn(None)

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource',
                         self.stack['BResource'].properties['Foo'])

        self.assertEqual(3, len(self.stack.resources))
        self.m.VerifyAll()

    def test_update_by_reference_and_rollback_1(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the first instance
        '''
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {
                                  'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                                   'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)

        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'FnGetRefId')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        generic_rsrc.ResourceWithProps.FnGetRefId().MultipleTimes().AndReturn(
            'AResource')

        # mock to make the replace fail when creating the replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        self.m.VerifyAll()

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

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': 'abc'}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {
                                  'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'ResourceTypeA',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                                   'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)

        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.ROLLBACK, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_update_failure_recovery(self):
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
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                 'AResource': {'Type': 'ResourceTypeA',
                               'Properties': {'Foo': 'smelly'}},
                 'BResource': {'Type': 'ResourceWithPropsType',
                               'Properties': {
                                   'Foo': {'Ref': 'AResource'}}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=True)

        self.stack.store()
        self.stack.create()

        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        self.m.StubOutWithMock(ResourceTypeA, 'handle_delete')

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        # delete the old resource on the second update
        generic_rsrc.ResourceWithProps.handle_delete()
        ResourceTypeA.handle_delete()
        generic_rsrc.ResourceWithProps.handle_create()
        generic_rsrc.ResourceWithProps.handle_delete()

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])

        self.stack = parser.Stack.load(self.ctx, self.stack.id)
        updated_stack2 = parser.Stack(self.ctx, 'updated_stack',
                                      template.Template(tmpl2),
                                      disable_rollback=True)

        self.stack.update(updated_stack2)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource2',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_update_failure_recovery_new_param(self):
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

        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'abc-param': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': {'Ref': 'abc-param'}}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': {'Ref': 'AResource'}}}
            }
        }
        env1 = environment.Environment({'abc-param': 'abc'})
        tmpl2 = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'smelly-param': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': {'Ref': 'smelly-param'}}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': {'Ref': 'AResource'}}}
            }
        }
        env2 = environment.Environment({'smelly-param': 'smelly'})

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl), env1,
                                  disable_rollback=True)

        self.stack.store()
        self.stack.create()

        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        self.m.StubOutWithMock(ResourceTypeA, 'handle_delete')

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        # delete the old resource on the second update
        generic_rsrc.ResourceWithProps.handle_delete()
        ResourceTypeA.handle_delete()
        generic_rsrc.ResourceWithProps.handle_create()
        generic_rsrc.ResourceWithProps.handle_delete()

        self.m.ReplayAll()

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2), env2,
                                     disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])

        self.stack = parser.Stack.load(self.ctx, self.stack.id)
        updated_stack2 = parser.Stack(self.ctx, 'updated_stack',
                                      template.Template(tmpl2), env2,
                                      disable_rollback=True)

        self.stack.update(updated_stack2)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)

        self.stack = parser.Stack.load(self.ctx, self.stack.id)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource2',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

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
        self.stack = parser.Stack(self.ctx, 'update_test_stack',
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

        self.assertEqual((parser.Stack.CREATE, parser.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl),
                                     disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_update_replace_parameters(self):
        '''
        assertion:
        changes in static environment parameters
        are not ignored and can cause dependent resources to be updated.
        '''
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Parameters': {'AParam': {'Type': 'String'}},
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
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl),
                                     environment.Environment(env2))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])

    def test_update_deletion_policy(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'Bar'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        resource_id = self.stack['AResource'].id

        new_tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'DeletionPolicy': 'Retain',
                                  'Properties': {'Foo': 'Bar'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(new_tmpl))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(resource_id, self.stack['AResource'].id)

    def test_update_deletion_policy_no_handle_update(self):

        class ResourceWithNoUpdate(resource.Resource):
            properties_schema = {'Foo': {'Type': 'String'}}

        resource._register_class('ResourceWithNoUpdate',
                                 ResourceWithNoUpdate)

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceWithNoUpdate',
                              'Properties': {'Foo': 'Bar'}}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        resource_id = self.stack['AResource'].id

        new_tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {
                    'AResource': {'Type': 'ResourceWithNoUpdate',
                                  'DeletionPolicy': 'Retain',
                                  'Properties': {'Foo': 'Bar'}}}}

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(new_tmpl))
        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(resource_id, self.stack['AResource'].id)

    def test_update_template_format_version(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'AParam': {'Type': 'String', 'Default': 'abc'}},
            'Resources': {
                'AResource': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {'Foo': {'Ref': 'AParam'}}
                },
            }
        }

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        tmpl2 = {
            'heat_template_version': '2013-05-23',
            'parameters': {
                'AParam': {'type': 'string', 'default': 'foo'}},
            'resources': {
                'AResource': {
                    'type': 'ResourceWithPropsType',
                    'properties': {'Foo': {'get_param': 'AParam'}}
                }
            }
        }

        updated_stack = parser.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2))

        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((parser.Stack.UPDATE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('foo', self.stack['AResource'].properties['Foo'])
        self.m.VerifyAll()

    def test_stack_create_timeout(self):
        self.m.StubOutWithMock(scheduler.DependencyTaskGroup, '__call__')
        self.m.StubOutWithMock(scheduler, 'wallclock')

        stack = parser.Stack(self.ctx, 's', self.tmpl)

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

        self.assertEqual((parser.Stack.CREATE, parser.Stack.FAILED),
                         stack.state)
        self.assertEqual('Create timed out', stack.status_reason)

        self.m.VerifyAll()

    def test_stack_delete_timeout(self):
        stack = parser.Stack(self.ctx, 'delete_test',
                             self.tmpl)
        stack_id = stack.store()

        db_s = db_api.stack_get(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

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

        self.assertEqual((parser.Stack.DELETE, parser.Stack.FAILED),
                         stack.state)
        self.assertEqual('Delete timed out', stack.status_reason)

        self.m.VerifyAll()

    def test_stack_delete_resourcefailure(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_delete')
        exc = Exception('foo')
        generic_rsrc.GenericResource.handle_delete().AndRaise(exc)
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'delete_test_fail',
                                  parser.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.delete()

        self.assertEqual((self.stack.DELETE, self.stack.FAILED),
                         self.stack.state)
        self.assertEqual('Resource DELETE failed: Exception: foo',
                         self.stack.status_reason)
        self.m.VerifyAll()

    def test_stack_name_valid(self):
        stack = parser.Stack(self.ctx, 's', self.tmpl)
        self.assertIsInstance(stack, parser.Stack)
        stack = parser.Stack(self.ctx, 'stack123', self.tmpl)
        self.assertIsInstance(stack, parser.Stack)
        stack = parser.Stack(self.ctx, 'test.stack', self.tmpl)
        self.assertIsInstance(stack, parser.Stack)
        stack = parser.Stack(self.ctx, 'test_stack', self.tmpl)
        self.assertIsInstance(stack, parser.Stack)
        stack = parser.Stack(self.ctx, 'TEST', self.tmpl)
        self.assertIsInstance(stack, parser.Stack)
        stack = parser.Stack(self.ctx, 'test-stack', self.tmpl)
        self.assertIsInstance(stack, parser.Stack)

    def test_stack_name_invalid(self):
        self.assertRaises(ValueError, parser.Stack, self.ctx, '_foo',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, '1bad',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, '.kcats',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test stack',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, ' teststack',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, '^-^',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, '\"stack\"',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, '1234',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'cat|dog',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, '$(foo)',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test/stack',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test\stack',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test::stack',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test;stack',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, 'test~stack',
                          self.tmpl)
        self.assertRaises(ValueError, parser.Stack, self.ctx, '#test',
                          self.tmpl)

    def test_resource_state_get_att(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {'AResource': {'Type': 'GenericResourceType'}},
            'Outputs': {'TestOutput': {'Value': {
                'Fn::GetAtt': ['AResource', 'Foo']}}
            }
        }

        self.stack = parser.Stack(self.ctx, 'resource_state_get_att',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
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

        self.stack = parser.Stack(self.ctx, 'depends_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
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

        self.stack = parser.Stack(self.ctx, 'depends_test_stack',
                                  template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        for r in ['AResource', 'BResource', 'CResource']:
            self.assertEqual(['DResource'],
                             self.stack[r].required_by())

    def test_store_saves_owner(self):
        """
        The owner_id attribute of Store is saved to the database when stored.
        """
        self.stack = parser.Stack(
            self.ctx, 'owner_stack', self.tmpl)
        stack_ownee = parser.Stack(
            self.ctx, 'ownee_stack', self.tmpl,
            owner_id=self.stack.id)
        stack_ownee.store()
        db_stack = db_api.stack_get(self.ctx, stack_ownee.id)
        self.assertEqual(self.stack.id, db_stack.owner_id)

    def test_init_user_creds_id(self):
        ctx_init = utils.dummy_context(user='my_user',
                                       password='my_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = db_api.user_creds_create(ctx_init)
        self.stack = parser.Stack(self.ctx, 'creds_init', self.tmpl,
                                  user_creds_id=creds.id)
        self.stack.store()
        self.assertEqual(creds.id, self.stack.user_creds_id)
        ctx_expected = ctx_init.to_dict()
        ctx_expected['auth_token'] = None
        self.assertEqual(ctx_expected, self.stack.stored_context().to_dict())

    def test_store_saves_creds(self):
        """
        A user_creds entry is created on first stack store
        """
        self.stack = parser.Stack(
            self.ctx, 'creds_stack', self.tmpl)
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
            FakeKeystoneClient(user_id='auser123'))
        self.m.ReplayAll()

        self.stack = parser.Stack(
            self.ctx, 'creds_stack', self.tmpl)
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
        creds = db_api.user_creds_create(ctx_init)
        self.stack = parser.Stack(self.ctx, 'creds_init', self.tmpl,
                                  user_creds_id=creds.id)
        self.stack.store()
        self.assertEqual(creds.id, self.stack.user_creds_id)
        backup = self.stack._backup_stack()
        self.assertEqual(creds.id, backup.user_creds_id)

    def test_stored_context_err(self):
        """
        Test stored_context error path.
        """
        self.stack = parser.Stack(self.ctx, 'creds_stack', self.tmpl)
        ex = self.assertRaises(exception.Error, self.stack.stored_context)
        expected_err = 'Attempt to use stored_context with no user_creds'
        self.assertEqual(expected_err, six.text_type(ex))

    def test_store_gets_username_from_stack(self):
        self.stack = parser.Stack(self.ctx, 'username_stack',
                                  self.tmpl, username='foobar')
        self.ctx.username = 'not foobar'
        self.stack.store()
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertEqual('foobar', db_stack.username)

    def test_store_backup_true(self):
        self.stack = parser.Stack(self.ctx, 'username_stack',
                                  self.tmpl, username='foobar')
        self.ctx.username = 'not foobar'
        self.stack.store(backup=True)
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertTrue(db_stack.backup)

    def test_store_backup_false(self):
        self.stack = parser.Stack(self.ctx, 'username_stack',
                                  self.tmpl, username='foobar')
        self.ctx.username = 'not foobar'
        self.stack.store(backup=False)
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertFalse(db_stack.backup)

    def test_init_stored_context_false(self):
        ctx_init = utils.dummy_context(user='mystored_user',
                                       password='mystored_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = db_api.user_creds_create(ctx_init)
        self.stack = parser.Stack(self.ctx, 'creds_store1', self.tmpl,
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
        creds = db_api.user_creds_create(ctx_init)
        self.stack = parser.Stack(self.ctx, 'creds_store2', self.tmpl,
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
        creds = db_api.user_creds_create(ctx_init)
        self.stack = parser.Stack(self.ctx, 'creds_store3', self.tmpl,
                                  user_creds_id=creds.id)
        self.stack.store()

        load_stack = parser.Stack.load(self.ctx, stack_id=self.stack.id,
                                       use_stored_context=False)
        self.assertEqual(self.ctx.to_dict(), load_stack.context.to_dict())

    def test_load_stored_context_true(self):
        ctx_init = utils.dummy_context(user='mystored_user',
                                       password='mystored_pass')
        ctx_init.request_id = self.ctx.request_id
        creds = db_api.user_creds_create(ctx_init)
        self.stack = parser.Stack(self.ctx, 'creds_store4', self.tmpl,
                                  user_creds_id=creds.id)
        self.stack.store()
        ctx_expected = ctx_init.to_dict()
        ctx_expected['auth_token'] = None

        load_stack = parser.Stack.load(self.ctx, stack_id=self.stack.id,
                                       use_stored_context=True)
        self.assertEqual(ctx_expected, load_stack.context.to_dict())

    def test_load_honors_owner(self):
        """
        Loading a stack from the database will set the owner_id of the
        resultant stack appropriately.
        """
        self.stack = parser.Stack(
            self.ctx, 'owner_stack', self.tmpl)
        stack_ownee = parser.Stack(
            self.ctx, 'ownee_stack', self.tmpl,
            owner_id=self.stack.id)
        stack_ownee.store()

        saved_stack = parser.Stack.load(self.ctx, stack_id=stack_ownee.id)
        self.assertEqual(self.stack.id, saved_stack.owner_id)

    def test_requires_deferred_auth(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'},
                              'BResource': {'Type': 'GenericResourceType'},
                              'CResource': {'Type': 'GenericResourceType'}}}

        self.stack = parser.Stack(self.ctx, 'update_test_stack',
                                  template.Template(tmpl),
                                  disable_rollback=False)

        self.assertFalse(self.stack.requires_deferred_auth())

        self.stack['CResource'].requires_deferred_auth = True
        self.assertTrue(self.stack.requires_deferred_auth())

    def test_stack_user_project_id_default(self):
        self.stack = parser.Stack(self.ctx, 'user_project_none',
                                  self.tmpl)
        self.stack.store()
        self.assertIsNone(self.stack.stack_user_project_id)
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertIsNone(db_stack.stack_user_project_id)

    def test_stack_user_project_id_constructor(self):
        self.stub_keystoneclient()
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'user_project_init',
                                  self.tmpl,
                                  stack_user_project_id='aproject1234')
        self.stack.store()
        self.assertEqual('aproject1234', self.stack.stack_user_project_id)
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertEqual('aproject1234', db_stack.stack_user_project_id)

        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_stack_user_project_id_delete_fail(self):

        class FakeKeystoneClientFail(FakeKeystoneClient):
            def delete_stack_domain_project(self, project_id):
                raise kc_exceptions.Forbidden("Denied!")

        self.m.StubOutWithMock(keystone.KeystoneClientPlugin, '_create')
        keystone.KeystoneClientPlugin._create().AndReturn(
            FakeKeystoneClientFail())
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'user_project_init',
                                  self.tmpl,
                                  stack_user_project_id='aproject1234')
        self.stack.store()
        self.assertEqual('aproject1234', self.stack.stack_user_project_id)
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertEqual('aproject1234', db_stack.stack_user_project_id)

        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.FAILED),
                         self.stack.state)
        self.assertIn('Error deleting project', self.stack.status_reason)
        self.m.VerifyAll()

    def test_stack_user_project_id_setter(self):
        self.stub_keystoneclient()
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'user_project_init',
                                  self.tmpl)
        self.stack.store()
        self.assertIsNone(self.stack.stack_user_project_id)
        self.stack.set_stack_user_project_id(project_id='aproject456')
        self.assertEqual('aproject456', self.stack.stack_user_project_id)
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertEqual('aproject456', db_stack.stack_user_project_id)

        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_stack_user_project_id_create(self):
        self.stub_keystoneclient()
        self.m.ReplayAll()

        self.stack = parser.Stack(self.ctx, 'user_project_init',
                                  self.tmpl)
        self.stack.store()
        self.assertIsNone(self.stack.stack_user_project_id)
        self.stack.create_stack_user_project_id()

        self.assertEqual('aprojectid', self.stack.stack_user_project_id)
        db_stack = db_api.stack_get(self.ctx, self.stack.id)
        self.assertEqual('aprojectid', db_stack.stack_user_project_id)

        self.stack.delete()
        self.assertEqual((parser.Stack.DELETE, parser.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_preview_resources_returns_list_of_resource_previews(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = parser.Stack(self.ctx, 'preview_stack',
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

        self.stack = parser.Stack(self.ctx, 'stack_with_correct_outputs',
                                  template.Template(tmpl))

        self.stack.store()
        self.stack.create()

        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
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

        self.stack = parser.Stack(self.ctx, 'stack_with_incorrect_outputs',
                                  template.Template(tmpl))

        self.stack.store()
        self.stack.create()

        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
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

        self.stack = parser.Stack(self.ctx, 'stack_with_custom_constraint',
                                  template.Template(tmpl),
                                  environment.Environment({'flavor': 'dummy'}))

        self.stack.validate()
        self.stack.store()
        self.stack.create()
        stack_id = self.stack.id

        self.m.VerifyAll()

        self.assertEqual((parser.Stack.CREATE, parser.Stack.COMPLETE),
                         self.stack.state)

        loaded_stack = parser.Stack.load(self.ctx, stack_id=self.stack.id)
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

        self.stack = parser.Stack(self.ctx, 'snapshot_stack',
                                  template.Template(tmpl))
        data = self.stack.prepare_abandon()
        fake_snapshot = collections.namedtuple('Snapshot', ('data',))(data)
        self.stack.delete_snapshot(fake_snapshot)
        self.assertEqual([data['resources']['AResource']], snapshots)

    def test_incorrect_outputs_cfn_get_attr(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                'AResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': 'abc'}}},
                'Outputs': {
                    'Resource_attr': {
                        'Value': {
                            'Fn::GetAtt': ['AResource', 'Bar']}}}}

        self.stack = parser.Stack(self.ctx, 'stack_with_correct_outputs',
                                  template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertEqual('Output validation error: The Referenced Attribute '
                         '(AResource Bar) is incorrect.',
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

        self.stack = parser.Stack(self.ctx, 'stack_with_correct_outputs',
                                  template.Template(tmpl))

        ex = self.assertRaises(exception.StackValidationFailed,
                               self.stack.validate)

        self.assertEqual('Output validation error: The Referenced Attribute '
                         '(AResource Bar) is incorrect.',
                         six.text_type(ex))
