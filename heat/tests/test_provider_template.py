
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
import os
import uuid
import yaml

import testscenarios

from heat.common import exception
from heat.common import template_format
from heat.common import urlfetch

from heat.engine import environment
from heat.engine import parser
from heat.engine import properties
from heat.engine import resource
from heat.engine import resources
from heat.engine.resources import template_resource

from heat.tests.common import HeatTestCase
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


load_tests = testscenarios.load_tests_apply_scenarios


class MyCloudResource(generic_rsrc.GenericResource):
    pass


class ProviderTemplateTest(HeatTestCase):
    def setUp(self):
        super(ProviderTemplateTest, self).setUp()
        utils.setup_dummy_db()
        resource._register_class('OS::ResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('myCloud::ResourceType',
                                 MyCloudResource)

    def test_get_os_empty_registry(self):
        # assertion: with an empty environment we get the correct
        # default class.
        env_str = {'resource_registry': {}}
        env = environment.Environment(env_str)
        cls = env.get_class('OS::ResourceType', 'fred')
        self.assertEqual(generic_rsrc.GenericResource, cls)

    def test_get_mine_global_map(self):
        # assertion: with a global rule we get the "mycloud" class.
        env_str = {'resource_registry': {"OS::*": "myCloud::*"}}
        env = environment.Environment(env_str)
        cls = env.get_class('OS::ResourceType', 'fred')
        self.assertEqual(MyCloudResource, cls)

    def test_get_mine_type_map(self):
        # assertion: with a global rule we get the "mycloud" class.
        env_str = {'resource_registry': {
            "OS::ResourceType": "myCloud::ResourceType"}}
        env = environment.Environment(env_str)
        cls = env.get_class('OS::ResourceType', 'fred')
        self.assertEqual(MyCloudResource, cls)

    def test_get_mine_resource_map(self):
        # assertion: with a global rule we get the "mycloud" class.
        env_str = {'resource_registry': {'resources': {'fred': {
            "OS::ResourceType": "myCloud::ResourceType"}}}}
        env = environment.Environment(env_str)
        cls = env.get_class('OS::ResourceType', 'fred')
        self.assertEqual(MyCloudResource, cls)

    def test_get_os_no_match(self):
        # assertion: make sure 'fred' doesn't match 'jerry'.
        env_str = {'resource_registry': {'resources': {'jerry': {
            "OS::ResourceType": "myCloud::ResourceType"}}}}
        env = environment.Environment(env_str)
        cls = env.get_class('OS::ResourceType', 'fred')
        self.assertEqual(generic_rsrc.GenericResource, cls)

    def test_to_parameters(self):
        """Tests property conversion to parameter values."""
        provider = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'Foo': {'Type': 'String'},
                'AList': {'Type': 'CommaDelimitedList'},
                'ListEmpty': {'Type': 'CommaDelimitedList'},
                'ANum': {'Type': 'Number'},
                'AMap': {'Type': 'Json'},
            },
            'Outputs': {
                'Foo': {'Value': 'bar'},
            },
        }

        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            attributes_schema = {"Foo": "A test attribute"}
            properties_schema = {
                "Foo": {"Type": "String"},
                "AList": {"Type": "List"},
                "ListEmpty": {"Type": "List"},
                "ANum": {"Type": "Number"},
                "AMap": {"Type": "Map"}
            }

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}, files=files), env=env,
                             stack_id=str(uuid.uuid4()))

        map_prop_val = {
            "key1": "val1",
            "key2": ["lval1", "lval2", "lval3"],
            "key3": {
                "key4": 4,
                "key5": False
            }
        }
        json_snippet = {
            "Type": "DummyResource",
            "Properties": {
                "Foo": "Bar",
                "AList": ["one", "two", "three"],
                "ListEmpty": [],
                "ANum": 5,
                "AMap": map_prop_val
            }
        }
        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        temp_res.validate()
        converted_params = temp_res.child_params()
        self.assertTrue(converted_params)
        for key in DummyResource.properties_schema:
            self.assertIn(key, converted_params)
        # verify String conversion
        self.assertEqual("Bar", converted_params.get("Foo"))
        # verify List conversion
        self.assertEqual(",".join(json_snippet.get("Properties",
                                                   {}).get("AList",
                                                           [])),
                         converted_params.get("AList"))
        # verify Number conversion
        self.assertEqual(5, converted_params.get("ANum"))
        # verify Map conversion
        self.assertEqual(map_prop_val, converted_params.get("AMap"))

    def test_attributes_extra(self):
        provider = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Outputs': {
                'Foo': {'Value': 'bar'},
                'Blarg': {'Value': 'wibble'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {}
            attributes_schema = {"Foo": "A test attribute"}

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}, files=files), env=env,
                             stack_id=str(uuid.uuid4()))

        json_snippet = {
            "Type": "DummyResource",
        }

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertIsNone(temp_res.validate())

    def test_attributes_missing(self):
        provider = {
            'Outputs': {
                'Blarg': {'Value': 'wibble'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {}
            attributes_schema = {"Foo": "A test attribute"}

        json_snippet = {
            "Type": "DummyResource",
        }

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}, files=files), env=env,
                             stack_id=str(uuid.uuid4()))

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertRaises(exception.StackValidationFailed,
                          temp_res.validate)

    def test_properties_normal(self):
        provider = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'Foo': {'Type': 'String'},
                'Blarg': {'Type': 'String', 'Default': 'wibble'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {"Foo":
                                 properties.Schema(properties.Schema.STRING,
                                                   required=True)}
            attributes_schema = {}

        json_snippet = {
            "Type": "DummyResource",
            "Properties": {
                "Foo": "bar",
            },
        }

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}, files=files), env=env,
                             stack_id=str(uuid.uuid4()))

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertIsNone(temp_res.validate())

    def test_properties_missing(self):
        provider = {
            'Parameters': {
                'Blarg': {'Type': 'String', 'Default': 'wibble'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {"Foo":
                                 properties.Schema(properties.Schema.STRING,
                                                   required=True)}
            attributes_schema = {}

        json_snippet = {
            "Type": "DummyResource",
        }

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}, files=files), env=env,
                             stack_id=str(uuid.uuid4()))

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertRaises(exception.StackValidationFailed,
                          temp_res.validate)

    def test_properties_extra_required(self):
        provider = {
            'Parameters': {
                'Blarg': {'Type': 'String'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {}
            attributes_schema = {}

        json_snippet = {
            "Type": "DummyResource",
            "Properties": {
                "Blarg": "wibble",
            },
        }

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}, files=files), env=env,
                             stack_id=str(uuid.uuid4()))

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertRaises(exception.StackValidationFailed,
                          temp_res.validate)

    def test_properties_type_mismatch(self):
        provider = {
            'Parameters': {
                'Foo': {'Type': 'String'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {"Foo":
                                 properties.Schema(properties.Schema.MAP)}
            attributes_schema = {}

        json_snippet = {
            "Type": "DummyResource",
            "Properties": {
                "Foo": "bar",
            },
        }

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}, files=files), env=env,
                             stack_id=str(uuid.uuid4()))

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertRaises(exception.StackValidationFailed,
                          temp_res.validate)

    def test_get_template_resource(self):
        # assertion: if the name matches {.yaml|.template} we get the
        # TemplateResource class.
        env_str = {'resource_registry': {'resources': {'fred': {
            "OS::ResourceType": "some_magic.yaml"}}}}
        env = environment.Environment(env_str)
        cls = env.get_class('OS::ResourceType', 'fred')
        self.assertEqual(template_resource.TemplateResource, cls)

    def test_get_template_resource_class(self):
        test_templ_name = 'file:///etc/heatr/frodo.yaml'
        minimal_temp = json.dumps({'HeatTemplateFormatVersion': '2012-12-12',
                                   'Parameters': {},
                                   'Resources': {}})
        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('file',)).AndReturn(minimal_temp)
        self.m.ReplayAll()

        env_str = {'resource_registry': {'resources': {'fred': {
            "OS::ResourceType": test_templ_name}}}}
        env = environment.Environment(env_str)
        cls = env.get_class('OS::ResourceType', 'fred')
        self.assertNotEqual(template_resource.TemplateResource, cls)
        self.assertTrue(issubclass(cls, template_resource.TemplateResource))
        self.assertTrue(hasattr(cls, "properties_schema"))
        self.assertTrue(hasattr(cls, "attributes_schema"))
        self.m.VerifyAll()

    def test_template_as_resource(self):
        """
        Test that the resulting resource has the right prop and attrib schema.

        Note that this test requires the Wordpress_Single_Instance.yaml
        template in the templates directory since we want to test using a
        non-trivial template.
        """
        test_templ_name = "WordPress_Single_Instance.yaml"
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'templates', test_templ_name)
        # check if its in the directory list vs. exists to work around
        # case-insensitive file systems
        self.assertIn(test_templ_name, os.listdir(os.path.dirname(path)))
        with open(path) as test_templ_file:
            test_templ = test_templ_file.read()
        self.assertTrue(test_templ, "Empty test template")
        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('file',)).AndRaise(IOError)
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https')).AndReturn(test_templ)
        parsed_test_templ = template_format.parse(test_templ)
        self.m.ReplayAll()
        json_snippet = {
            "Type": test_templ_name,
            "Properties": {
                "KeyName": "mykeyname",
                "DBName": "wordpress1",
                "DBUsername": "wpdbuser",
                "DBPassword": "wpdbpass",
                "DBRootPassword": "wpdbrootpass",
                "LinuxDistribution": "U10"
            }
        }
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}), stack_id=str(uuid.uuid4()))
        templ_resource = resource.Resource("test_templ_resource", json_snippet,
                                           stack)
        self.m.VerifyAll()
        self.assertIsInstance(templ_resource,
                              template_resource.TemplateResource)
        for prop in parsed_test_templ.get("Parameters", {}):
            self.assertIn(prop, templ_resource.properties)
        for attrib in parsed_test_templ.get("Outputs", {}):
            self.assertIn(attrib, templ_resource.attributes)
        for k, v in json_snippet.get("Properties").items():
            self.assertEqual(v, templ_resource.properties[k])
        self.assertEqual(
            {'WordPress_Single_Instance.yaml':
             'WordPress_Single_Instance.yaml', 'resources': {}},
            stack.env.user_env_as_dict()["resource_registry"])
        self.assertNotIn('WordPress_Single_Instance.yaml',
                         resources.global_env().registry._registry)

    def test_persisted_unregistered_provider_templates(self):
        """
        Test that templates persisted in the database prior to
        https://review.openstack.org/#/c/79953/1 are registered correctly.
        """
        env = {'resource_registry': {'http://example.com/test.template': None,
                                     'resources': {}}}
        #A KeyError will be thrown prior to this fix.
        environment.Environment(env=env)

    def test_system_template_retrieve_by_file(self):
        # make sure that a TemplateResource defined in the global environment
        # can be created and the template retrieved using the "file:"
        # scheme.
        g_env = resources.global_env()
        test_templ_name = 'file:///etc/heatr/frodo.yaml'
        g_env.load({'resource_registry':
                   {'Test::Frodo': test_templ_name}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}),
                             stack_id=str(uuid.uuid4()))

        minimal_temp = json.dumps({'HeatTemplateFormatVersion': '2012-12-12',
                                   'Parameters': {},
                                   'Resources': {}})
        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https',
                                      'file')).AndReturn(minimal_temp)
        self.m.ReplayAll()

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      {"Type": 'Test::Frodo'},
                                                      stack)
        self.assertIsNone(temp_res.validate())
        self.m.VerifyAll()

    def test_user_template_not_retrieved_by_file(self):
        # make sure that a TemplateResource defined in the user environment
        # can NOT be retrieved using the "file:" scheme, validation should fail
        env = environment.Environment()
        test_templ_name = 'file:///etc/heatr/flippy.yaml'
        env.load({'resource_registry':
                  {'Test::Flippy': test_templ_name}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}), env=env,
                             stack_id=str(uuid.uuid4()))

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      {"Type": 'Test::Flippy'},
                                                      stack)

        self.assertRaises(exception.StackValidationFailed, temp_res.validate)

    def test_system_template_retrieve_fail(self):
        # make sure that a TemplateResource defined in the global environment
        # fails gracefully if the template file specified is inaccessible
        # we should be able to create the TemplateResource object, but
        # validation should fail, when the second attempt to access it is
        # made in validate()
        g_env = resources.global_env()
        test_templ_name = 'file:///etc/heatr/frodo.yaml'
        g_env.load({'resource_registry':
                   {'Test::Frodo': test_templ_name}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}),
                             stack_id=str(uuid.uuid4()))

        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https',
                                      'file')).AndRaise(IOError)
        self.m.ReplayAll()

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      {"Type": 'Test::Frodo'},
                                                      stack)
        self.assertRaises(exception.StackValidationFailed, temp_res.validate)
        self.m.VerifyAll()

    def test_user_template_retrieve_fail(self):
        # make sure that a TemplateResource defined in the user environment
        # fails gracefully if the template file specified is inaccessible
        # we should be able to create the TemplateResource object, but
        # validation should fail, when the second attempt to access it is
        # made in validate()
        env = environment.Environment()
        test_templ_name = 'http://heatr/noexist.yaml'
        env.load({'resource_registry':
                  {'Test::Flippy': test_templ_name}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}), env=env,
                             stack_id=str(uuid.uuid4()))

        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https')).AndRaise(IOError)
        self.m.ReplayAll()

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      {"Type": 'Test::Flippy'},
                                                      stack)
        self.assertRaises(exception.StackValidationFailed, temp_res.validate)
        self.m.VerifyAll()

    def test_user_template_retrieve_fail_ext(self):
        # make sure that a TemplateResource defined in the user environment
        # fails gracefully if the template file is the wrong extension
        # we should be able to create the TemplateResource object, but
        # validation should fail, when the second attempt to access it is
        # made in validate()
        env = environment.Environment()
        test_templ_name = 'http://heatr/letter_to_granny.docx'
        env.load({'resource_registry':
                  {'Test::Flippy': test_templ_name}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}), env=env,
                             stack_id=str(uuid.uuid4()))

        self.m.ReplayAll()

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      {"Type": 'Test::Flippy'},
                                                      stack)
        self.assertRaises(exception.StackValidationFailed, temp_res.validate)
        self.m.VerifyAll()


class NestedProvider(HeatTestCase):
    """Prove that we can use the registry in a nested provider."""

    def setUp(self):
        super(NestedProvider, self).setUp()
        utils.setup_dummy_db()

    def test_nested_env(self):
        main_templ = '''
heat_template_version: 2013-05-23
resources:
  secret2:
    type: My::NestedSecret
outputs:
  secret1:
    value: { get_attr: [secret1, value] }
'''

        nested_templ = '''
heat_template_version: 2013-05-23
resources:
  secret2:
    type: My::Secret
outputs:
  value:
    value: { get_attr: [secret2, value] }
'''

        env_templ = '''
resource_registry:
  "My::Secret": "OS::Heat::RandomString"
  "My::NestedSecret": nested.yaml
'''

        env = environment.Environment()
        env.load(yaml.load(env_templ))
        templ = parser.Template(template_format.parse(main_templ),
                                files={'nested.yaml': nested_templ})
        stack = parser.Stack(utils.dummy_context(),
                             utils.random_name(),
                             templ, env=env)
        stack.store()
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)

    def test_no_infinite_recursion(self):
        """Prove that we can override a python resource.

        And use that resource within the template resource.
        """

        main_templ = '''
heat_template_version: 2013-05-23
resources:
  secret2:
    type: OS::Heat::RandomString
outputs:
  secret1:
    value: { get_attr: [secret1, value] }
'''

        nested_templ = '''
heat_template_version: 2013-05-23
resources:
  secret2:
    type: OS::Heat::RandomString
outputs:
  value:
    value: { get_attr: [secret2, value] }
'''

        env_templ = '''
resource_registry:
  "OS::Heat::RandomString": nested.yaml
'''

        env = environment.Environment()
        env.load(yaml.load(env_templ))
        templ = parser.Template(template_format.parse(main_templ),
                                files={'nested.yaml': nested_templ})
        stack = parser.Stack(utils.dummy_context(),
                             utils.random_name(),
                             templ, env=env)
        stack.store()
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)


class ProviderTemplateUpdateTest(HeatTestCase):
    main_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_nested:
    Type: the.yaml
    Properties:
      one: my_name

Outputs:
  identifier:
    Value: {Ref: the_nested}
  value:
    Value: {'Fn::GetAtt': [the_nested, the_str]}
'''

    main_template_2 = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_nested:
    Type: the.yaml
    Properties:
      one: updated_name

Outputs:
  identifier:
    Value: {Ref: the_nested}
  value:
    Value: {'Fn::GetAtt': [the_nested, the_str]}
'''

    initial_tmpl = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  one:
    Default: foo
    Type: String
Resources:
  NestedResource:
    Type: OS::Heat::RandomString
    Properties:
      salt: {Ref: one}
Outputs:
  the_str:
    Value: {'Fn::GetAtt': [NestedResource, value]}
'''
    prop_change_tmpl = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  one:
    Default: yikes
    Type: String
  two:
    Default: foo
    Type: String
Resources:
  NestedResource:
    Type: OS::Heat::RandomString
    Properties:
      salt: {Ref: one}
Outputs:
  the_str:
    Value: {'Fn::GetAtt': [NestedResource, value]}
'''
    attr_change_tmpl = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  one:
    Default: foo
    Type: String
Resources:
  NestedResource:
    Type: OS::Heat::RandomString
    Properties:
      salt: {Ref: one}
Outputs:
  the_str:
    Value: {'Fn::GetAtt': [NestedResource, value]}
  something_else:
    Value: just_a_string
'''
    content_change_tmpl = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  one:
    Default: foo
    Type: String
Resources:
  NestedResource:
    Type: OS::Heat::RandomString
    Properties:
      salt: yum
Outputs:
  the_str:
    Value: {'Fn::GetAtt': [NestedResource, value]}
'''

    EXPECTED = (REPLACE, UPDATE, NOCHANGE) = ('replace', 'update', 'nochange')
    scenarios = [
        ('no_changes', dict(template=main_template,
                            provider=initial_tmpl,
                            expect=NOCHANGE)),
        ('main_tmpl_change', dict(template=main_template_2,
                                  provider=initial_tmpl,
                                  expect=UPDATE)),
        ('provider_change', dict(template=main_template,
                                 provider=content_change_tmpl,
                                 expect=UPDATE)),
        ('provider_props_change', dict(template=main_template,
                                       provider=prop_change_tmpl,
                                       expect=REPLACE)),
        ('provider_attr_change', dict(template=main_template,
                                      provider=attr_change_tmpl,
                                      expect=REPLACE)),
    ]

    def setUp(self):
        super(ProviderTemplateUpdateTest, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context('test_username', 'aaaa', 'password')

    def create_stack(self):
        t = template_format.parse(self.main_template)
        tmpl = parser.Template(t, files={'the.yaml': self.initial_tmpl})
        stack = parser.Stack(self.ctx, utils.random_name(), tmpl)
        stack.store()
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        return stack

    @utils.stack_delete_after
    def test_template_resource_update_template_schema(self):
        stack = self.create_stack()
        self.stack = stack
        initial_id = stack.output('identifier')
        initial_val = stack.output('value')
        tmpl = parser.Template(template_format.parse(self.template),
                               files={'the.yaml': self.provider})
        updated_stack = parser.Stack(self.ctx, stack.name, tmpl)
        stack.update(updated_stack)
        self.assertEqual(('UPDATE', 'COMPLETE'), stack.state)
        if self.expect == self.REPLACE:
            self.assertNotEqual(initial_id,
                                stack.output('identifier'))
            self.assertNotEqual(initial_val,
                                stack.output('value'))
        elif self.expect == self.NOCHANGE:
            self.assertEqual(initial_id,
                             stack.output('identifier'))
            self.assertEqual(initial_val,
                             stack.output('value'))
        else:
            self.assertEqual(initial_id,
                             stack.output('identifier'))
            self.assertNotEqual(initial_val,
                                stack.output('value'))
        self.m.VerifyAll()
