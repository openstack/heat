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


from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import template_resource

from heat.openstack.common import uuidutils

from heat.tests import generic_resource as generic_rsrc
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db


class MyCloudResource(generic_rsrc.GenericResource):
    pass


class ProviderTemplateTest(HeatTestCase):
    def setUp(self):
        super(ProviderTemplateTest, self).setUp()
        resource._register_class('OS::ResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('myCloud::ResourceType',
                                 MyCloudResource)

    def test_get_os_empty_registry(self):
        # assertion: with an empty environment we get the correct
        # default class.
        env_str = {'resource_registry': {}}
        env = environment.Environment(env_str)
        cls = resource.get_class('OS::ResourceType', 'fred', env)
        self.assertEqual(cls, generic_rsrc.GenericResource)

    def test_get_mine_global_map(self):
        # assertion: with a global rule we get the "mycloud" class.
        env_str = {'resource_registry': {"OS::*": "myCloud::*"}}
        env = environment.Environment(env_str)
        cls = resource.get_class('OS::ResourceType', 'fred', env)
        self.assertEqual(cls, MyCloudResource)

    def test_get_mine_type_map(self):
        # assertion: with a global rule we get the "mycloud" class.
        env_str = {'resource_registry': {
            "OS::ResourceType": "myCloud::ResourceType"}}
        env = environment.Environment(env_str)
        cls = resource.get_class('OS::ResourceType', 'fred', env)
        self.assertEqual(cls, MyCloudResource)

    def test_get_mine_resource_map(self):
        # assertion: with a global rule we get the "mycloud" class.
        env_str = {'resource_registry': {'resources': {'fred': {
            "OS::ResourceType": "myCloud::ResourceType"}}}}
        env = environment.Environment(env_str)
        cls = resource.get_class('OS::ResourceType', 'fred', env)
        self.assertEqual(cls, MyCloudResource)

    def test_get_os_no_match(self):
        # assertion: make sure 'fred' doesn't match 'jerry'.
        env_str = {'resource_registry': {'resources': {'jerry': {
            "OS::ResourceType": "myCloud::ResourceType"}}}}
        env = environment.Environment(env_str)
        cls = resource.get_class('OS::ResourceType', 'fred', env)
        self.assertEqual(cls, generic_rsrc.GenericResource)

    def test_get_template_resource(self):
        # assertion: if the name matches {.yaml|.template} we get the
        # TemplateResource class.
        env_str = {'resource_registry': {'resources': {'fred': {
            "OS::ResourceType": "some_magic.yaml"}}}}
        env = environment.Environment(env_str)
        cls = resource.get_class('OS::ResourceType', 'fred', env)
        self.assertEqual(cls, template_resource.TemplateResource)

    def test_to_parameters(self):
        """Tests property conversion to parameter values."""
        setup_dummy_db()
        stack = parser.Stack(None, 'test_stack', parser.Template({}),
                             stack_id=uuidutils.generate_uuid())

        class DummyResource(object):
            attributes_schema = {"Foo": "A test attribute"}
            properties_schema = {
                "Foo": {"Type": "String"},
                "AList": {"Type": "List"},
                "ANum": {"Type": "Number"},
                "AMap": {"Type": "Map"}
            }

        map_prop_val = {
            "key1": "val1",
            "key2": ["lval1", "lval2", "lval3"],
            "key3": {
                "key4": 4,
                "key5": False
            }
        }
        json_snippet = {
            "Type": "test_resource.template",
            "Properties": {
                "Foo": "Bar",
                "AList": ["one", "two", "three"],
                "ANum": 5,
                "AMap": map_prop_val
            }
        }
        self.m.StubOutWithMock(template_resource.resource, "get_class")
        (template_resource.resource.get_class("test_resource.template")
         .AndReturn(DummyResource))
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
