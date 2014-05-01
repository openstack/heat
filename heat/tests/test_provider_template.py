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

import os
import json

from heat.common import exception
from heat.common import urlfetch
from heat.common import template_format

from heat.engine import environment
from heat.engine import parser
from heat.engine import properties
from heat.engine import resource
from heat.engine import resources
from heat.engine import scheduler
from heat.engine.resources import template_resource

from heat.openstack.common import uuidutils

from heat.tests import generic_resource as generic_rsrc
from heat.tests.common import HeatTestCase
from heat.tests import utils


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
                             stack_id=uuidutils.generate_uuid())

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
        converted_params = temp_res._to_parameters()
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
                             stack_id=uuidutils.generate_uuid())

        json_snippet = {
            "Type": "DummyResource",
        }

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertEqual(None, temp_res.validate())

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
                             stack_id=uuidutils.generate_uuid())

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertRaises(exception.StackValidationFailed,
                          temp_res.validate)

    def test_properties_normal(self):
        provider = {
            'Parameters': {
                'Foo': {'Type': 'String'},
                'Blarg': {'Type': 'String', 'Default': 'wibble'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {"Foo": properties.Schema(properties.STRING,
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
                             stack_id=uuidutils.generate_uuid())

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.assertEqual(None, temp_res.validate())

    def test_properties_missing(self):
        provider = {
            'Parameters': {
                'Blarg': {'Type': 'String', 'Default': 'wibble'},
            },
        }
        files = {'test_resource.template': json.dumps(provider)}

        class DummyResource(object):
            properties_schema = {"Foo": properties.Schema(properties.STRING,
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
                             stack_id=uuidutils.generate_uuid())

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
                             stack_id=uuidutils.generate_uuid())

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
            properties_schema = {"Foo": properties.Schema(properties.MAP)}
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
                             stack_id=uuidutils.generate_uuid())

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
        self.assertEqual(cls, template_resource.TemplateResource)

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
        stack = parser.Stack(None, 'test_stack', parser.Template({}),
                             stack_id=uuidutils.generate_uuid())
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
        self.assertNotIn('WordPress_Single_Instance.yaml',
                         resources.global_env().registry._registry)

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
                             stack_id=uuidutils.generate_uuid())

        minimal_temp = json.dumps({'Parameters': {}, 'Resources': {}})
        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https',
                                      'file')).AndReturn(minimal_temp)
        self.m.ReplayAll()

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      {"Type": 'Test::Frodo'},
                                                      stack)
        self.assertEqual(None, temp_res.validate())
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
                             stack_id=uuidutils.generate_uuid())

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
                             stack_id=uuidutils.generate_uuid())

        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https',
                                      'file')).AndRaise(IOError)
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
                             stack_id=uuidutils.generate_uuid())

        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https')).AndRaise(IOError)
        urlfetch.get(test_templ_name,
                     allowed_schemes=('http', 'https')).AndRaise(IOError)
        self.m.ReplayAll()

        temp_res = template_resource.TemplateResource('test_t_res',
                                                      {"Type": 'Test::Flippy'},
                                                      stack)
        self.assertRaises(exception.StackValidationFailed, temp_res.validate)
        self.m.VerifyAll()

    def create_stack(self, template):
        t = template_format.parse(template)
        stack = self.parse_stack(t)
        stack.create()
        self.assertEqual(stack.state, (stack.CREATE, stack.COMPLETE))
        return stack

    def parse_stack(self, t):
        ctx = utils.dummy_context('test_username', 'aaaa', 'password')
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        stack = parser.Stack(ctx, stack_name, tmpl)
        stack.store()
        return stack

    def test_template_resource_update(self):
        # assertion: updating a template resource is never destructive
        #            as it defers to the nested stack to determine if anything
        #            needs to be replaced.

        utils.setup_dummy_db()
        resource._register_class('GenericResource',
                                 generic_rsrc.GenericResource)

        templ_resource_name = 'http://server.test/the.yaml'
        test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_nested:
    Type: %s
    Properties:
      one: myname
''' % templ_resource_name

        self.m.StubOutWithMock(urlfetch, "get")
        urlfetch.get(templ_resource_name,
                     allowed_schemes=('http',
                                      'https')).MultipleTimes().\
            AndReturn('''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  one:
    Type: String
Resources:
  NestedResource:
    Type: GenericResource
Outputs:
  Foo:
    Value: {Ref: one}
''')

        self.m.ReplayAll()

        stack = self.create_stack(test_template)
        templ_resource = stack['the_nested']
        self.assertEqual('myname', templ_resource.FnGetAtt('Foo'))

        update_snippet = {
            "Type": templ_resource_name,
            "Properties": {
                "one": "yourname"
            }
        }
        # test that update() does NOT raise UpdateReplace.
        updater = scheduler.TaskRunner(templ_resource.update, update_snippet)
        self.assertEqual(None, updater())
        self.assertEqual('yourname', templ_resource.FnGetAtt('Foo'))

        self.m.VerifyAll()
