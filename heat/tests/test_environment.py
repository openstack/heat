# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import testtools

from heat.engine import environment


class EnvironmentTest(testtools.TestCase):
    def test_load_old_parameters(self):
        old = {u'a': u'ff', u'b': u'ss'}
        expected = {u'parameters': old,
                    u'resource_registry': {u'resources': {}}}
        env = environment.Environment(old)
        self.assertEqual(expected, env.user_env_as_dict())

    def test_load_new_env(self):
        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry': {u'OS::Food': 'fruity'}}
        env = environment.Environment(new_env)
        self.assertEqual(new_env, env.user_env_as_dict())

    def test_global_registry(self):
        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry': {u'OS::*': 'CloudX::*'}}
        env = environment.Environment(new_env)
        self.assertEqual('CloudX::Compute::Server',
                         env.get_resource_type('OS::Compute::Server',
                                               'my_db_server'))

    def test_map_one_resource_type(self):
        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry': {u'resources':
                                          {u'my_db_server':
                                           {u'OS::DBInstance': 'db.yaml'}}}}
        env = environment.Environment(new_env)
        self.assertEqual('db.yaml',
                         env.get_resource_type('OS::DBInstance',
                                               'my_db_server'))
        self.assertEqual('OS::Compute::Server',
                         env.get_resource_type('OS::Compute::Server',
                                               'my_other_server'))

    def test_map_all_resources_of_type(self):
        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry':
                   {u'OS::Networking::FloatingIP': 'OS::Nova::FloatingIP',
                    u'OS::Loadbalancer': 'lb.yaml'}}
        env = environment.Environment(new_env)
        self.assertEqual('OS::Nova::FloatingIP',
                         env.get_resource_type('OS::Networking::FloatingIP',
                                               'my_fip'))
