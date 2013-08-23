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

from heat.common import urlfetch
from heat.common import template_format

from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
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
        utils.setup_dummy_db()

        class DummyResource(object):
            attributes_schema = {"Foo": "A test attribute"}
            properties_schema = {
                "Foo": {"Type": "String"},
                "AList": {"Type": "List"},
                "ANum": {"Type": "Number"},
                "AMap": {"Type": "Map"}
            }

        env = environment.Environment()
        resource._register_class('DummyResource', DummyResource)
        env.load({'resource_registry':
                  {'DummyResource': 'test_resource.template'}})
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             parser.Template({}), env=env,
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
                "ANum": 5,
                "AMap": map_prop_val
            }
        }
        self.m.ReplayAll()
        temp_res = template_resource.TemplateResource('test_t_res',
                                                      json_snippet, stack)
        self.m.VerifyAll()
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
        urlfetch.get(test_templ_name).AndReturn(test_templ)
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
