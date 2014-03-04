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

import sys
import types

from heat.tests.common import HeatTestCase

from heat.engine import plugin_manager


def legacy_test_mapping():
    return {'foo': 'bar', 'baz': 'quux'}


def current_test_mapping():
    return {'blarg': 'wibble', 'bar': 'baz'}


def args_test_mapping(*args):
    return dict(enumerate(args))


def kwargs_test_mapping(**kwargs):
    return kwargs


def error_test_mapping():
    raise MappingTestError


class MappingTestError(Exception):
    pass


class TestPluginManager(HeatTestCase):

    @staticmethod
    def module():
        return sys.modules[__name__]

    def test_load_single_mapping(self):
        pm = plugin_manager.PluginMapping('current_test')
        self.assertEqual(current_test_mapping(),
                         pm.load_from_module(self.module()))

    def test_load_first_alternative_mapping(self):
        pm = plugin_manager.PluginMapping(['current_test', 'legacy_test'])
        self.assertEqual(current_test_mapping(),
                         pm.load_from_module(self.module()))

    def test_load_second_alternative_mapping(self):
        pm = plugin_manager.PluginMapping(['nonexist', 'current_test'])
        self.assertEqual(current_test_mapping(),
                         pm.load_from_module(self.module()))

    def test_load_mapping_args(self):
        pm = plugin_manager.PluginMapping('args_test', 'baz', 'quux')
        expected = {0: 'baz', 1: 'quux'}
        self.assertEqual(expected, pm.load_from_module(self.module()))

    def test_load_mapping_kwargs(self):
        pm = plugin_manager.PluginMapping('kwargs_test', baz='quux')
        self.assertEqual({'baz': 'quux'}, pm.load_from_module(self.module()))

    def test_load_mapping_non_existent(self):
        pm = plugin_manager.PluginMapping('nonexist')
        self.assertEqual({}, pm.load_from_module(self.module()))

    def test_load_mapping_error(self):
        pm = plugin_manager.PluginMapping('error_test')
        self.assertRaises(MappingTestError, pm.load_from_module, self.module())

    def test_modules(self):
        mgr = plugin_manager.PluginManager('heat.tests')

        for module in mgr.modules:
            self.assertEqual(types.ModuleType, type(module))
            self.assertTrue(module.__name__.startswith('heat.tests') or
                            module.__name__.startswith('heat.engine.plugins'))

    def test_load_all(self):
        mgr = plugin_manager.PluginManager('heat.tests')
        pm = plugin_manager.PluginMapping('current_test')

        all_items = pm.load_all(mgr)
        for item in current_test_mapping().iteritems():
            self.assertIn(item, all_items)
