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

import mock

from heat.engine import environment
from heat.engine import resources

from heat.tests import generic_resource
from heat.tests import common


class EnvironmentTest(common.HeatTestCase):
    def setUp(self):
        super(EnvironmentTest, self).setUp()
        self.g_env = resources.global_env()

    def test_load_old_parameters(self):
        old = {u'a': u'ff', u'b': u'ss'}
        expected = {u'parameters': old,
                    u'resource_registry': {u'resources': {}}}
        env = environment.Environment(old)
        self.assertEqual(expected, env.user_env_as_dict())

    def test_load_new_env(self):
        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry': {u'OS::Food': u'fruity.yaml',
                                          u'resources': {}}}
        env = environment.Environment(new_env)
        self.assertEqual(new_env, env.user_env_as_dict())

    def test_global_registry(self):
        self.g_env.register_class('CloudX::Compute::Server',
                                  generic_resource.GenericResource)
        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry': {u'OS::*': 'CloudX::*'}}
        env = environment.Environment(new_env)
        self.assertEqual('CloudX::Compute::Server',
                         env.get_resource_info('OS::Compute::Server',
                                               'my_db_server').name)

    def test_map_one_resource_type(self):
        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry': {u'resources':
                                          {u'my_db_server':
                                           {u'OS::DBInstance': 'db.yaml'}}}}
        env = environment.Environment(new_env)

        info = env.get_resource_info('OS::DBInstance', 'my_db_server')
        self.assertEqual('db.yaml', info.value)

    def test_map_all_resources_of_type(self):
        self.g_env.register_class('OS::Nova::FloatingIP',
                                  generic_resource.GenericResource)

        new_env = {u'parameters': {u'a': u'ff', u'b': u'ss'},
                   u'resource_registry':
                   {u'OS::Networking::FloatingIP': 'OS::Nova::FloatingIP',
                    u'OS::Loadbalancer': 'lb.yaml'}}

        env = environment.Environment(new_env)
        self.assertEqual('OS::Nova::FloatingIP',
                         env.get_resource_info('OS::Networking::FloatingIP',
                                               'my_fip').name)

    def test_resource_sort_order_len(self):
        new_env = {u'resource_registry': {u'resources': {u'my_fip': {
            u'OS::Networking::FloatingIP': 'ip.yaml'}}},
            u'OS::Networking::FloatingIP': 'OS::Nova::FloatingIP'}

        env = environment.Environment(new_env)
        self.assertEqual('ip.yaml',
                         env.get_resource_info('OS::Networking::FloatingIP',
                                               'my_fip').value)

    def test_env_load(self):
        new_env = {u'resource_registry': {u'resources': {u'my_fip': {
            u'OS::Networking::FloatingIP': 'ip.yaml'}}}}

        env = environment.Environment()
        self.assertEqual(None,
                         env.get_resource_info('OS::Networking::FloatingIP',
                                               'my_fip'))

        env.load(new_env)
        self.assertEqual('ip.yaml',
                         env.get_resource_info('OS::Networking::FloatingIP',
                                               'my_fip').value)


class GlobalEnvLoadingTest(common.HeatTestCase):

    def test_happy_path(self):
        list_dir = 'heat.engine.resources._list_environment_files'
        with mock.patch(list_dir) as m_ldir:
            m_ldir.return_value = ['a.yaml']
            env_dir = '/etc_etc/heat/enviroment.d'
            env_content = '{"resource_registry": {}}'

            with mock.patch('heat.engine.resources.open',
                            mock.mock_open(read_data=env_content),
                            create=True) as m_open:
                resources._load_global_environment(env_dir)

        m_ldir.assert_called_once_with(env_dir)
        m_open.assert_called_once_with('%s/a.yaml' % env_dir)

    def test_empty_env_dir(self):
        list_dir = 'heat.engine.resources._list_environment_files'
        with mock.patch(list_dir) as m_ldir:
            m_ldir.return_value = []
            env_dir = '/etc_etc/heat/enviroment.d'
            resources._load_global_environment(env_dir)

        m_ldir.assert_called_once_with(env_dir)

    def test_continue_on_ioerror(self):
        """assert we get all files processed even if there are
        processing exceptions.
        """
        list_dir = 'heat.engine.resources._list_environment_files'
        with mock.patch(list_dir) as m_ldir:
            m_ldir.return_value = ['a.yaml', 'b.yaml']
            env_dir = '/etc_etc/heat/enviroment.d'
            env_content = '{}'

            with mock.patch('heat.engine.resources.open',
                            mock.mock_open(read_data=env_content),
                            create=True) as m_open:
                m_open.side_effect = IOError
                resources._load_global_environment(env_dir)

        m_ldir.assert_called_once_with(env_dir)
        expected = [mock.call('%s/a.yaml' % env_dir),
                    mock.call('%s/b.yaml' % env_dir)]
        self.assertEqual(expected, m_open.call_args_list)

    def test_continue_on_parse_error(self):
        """assert we get all files processed even if there are
        processing exceptions.
        """
        list_dir = 'heat.engine.resources._list_environment_files'
        with mock.patch(list_dir) as m_ldir:
            m_ldir.return_value = ['a.yaml', 'b.yaml']
            env_dir = '/etc_etc/heat/enviroment.d'
            env_content = '{@$%#$%'

            with mock.patch('heat.engine.resources.open',
                            mock.mock_open(read_data=env_content),
                            create=True) as m_open:
                resources._load_global_environment(env_dir)

        m_ldir.assert_called_once_with(env_dir)
        expected = [mock.call('%s/a.yaml' % env_dir),
                    mock.call('%s/b.yaml' % env_dir)]
        self.assertEqual(expected, m_open.call_args_list)
