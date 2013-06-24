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
from heat.engine import resource
from heat.engine.resources import template_resource

from heat.tests import generic_resource as generic_rsrc
from heat.tests.common import HeatTestCase


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
