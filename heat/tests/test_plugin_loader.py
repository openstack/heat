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


import pkgutil
import sys
import unittest

import heat.engine
from heat.common import plugin_loader


class PluginLoaderTest(unittest.TestCase):
    def test_module_name(self):
        self.assertEqual(plugin_loader._module_name('foo.bar', 'blarg.wibble'),
                         'foo.bar.blarg.wibble')

    def test_create_subpackage_single_path(self):
        pkg_name = 'heat.engine.test_single_path'
        self.assertFalse(pkg_name in sys.modules)
        pkg = plugin_loader.create_subpackage('/tmp',
                                              'heat.engine',
                                              'test_single_path')
        self.assertTrue(pkg_name in sys.modules)
        self.assertEqual(sys.modules[pkg_name], pkg)
        self.assertEqual(pkg.__path__, ['/tmp'])
        self.assertEqual(pkg.__name__, pkg_name)

    def test_create_subpackage_path_list(self):
        path_list = ['/tmp']
        pkg_name = 'heat.engine.test_path_list'
        self.assertFalse(pkg_name in sys.modules)
        pkg = plugin_loader.create_subpackage('/tmp',
                                              'heat.engine',
                                              'test_path_list')
        self.assertTrue(pkg_name in sys.modules)
        self.assertEqual(sys.modules[pkg_name], pkg)
        self.assertEqual(pkg.__path__, path_list)
        self.assertFalse(pkg.__path__ is path_list)
        self.assertEqual(pkg.__name__, pkg_name)

    def test_import_module_existing(self):
        import heat.engine.service
        existing = heat.engine.service
        importer = pkgutil.ImpImporter(heat.engine.__path__[0])
        loaded = plugin_loader._import_module(importer,
                                              'heat.engine.service',
                                              heat.engine)
        self.assertTrue(loaded is existing)

    def test_import_module_garbage(self):
        importer = pkgutil.ImpImporter(heat.engine.__path__[0])
        self.assertEqual(plugin_loader._import_module(importer,
                                                      'wibble',
                                                      heat.engine),
                         None)
