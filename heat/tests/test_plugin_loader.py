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


import pkgutil
import sys

import mock

from heat.common import plugin_loader
import heat.engine
from heat.tests import common


class PluginLoaderTest(common.HeatTestCase):
    def test_module_name(self):
        self.assertEqual('foo.bar.blarg.wibble',
                         plugin_loader._module_name('foo.bar', 'blarg.wibble'))

    def test_create_subpackage_single_path(self):
        pkg_name = 'heat.engine.test_single_path'
        self.assertNotIn(pkg_name, sys.modules)
        pkg = plugin_loader.create_subpackage('/tmp',
                                              'heat.engine',
                                              'test_single_path')
        self.assertIn(pkg_name, sys.modules)
        self.assertEqual(sys.modules[pkg_name], pkg)
        self.assertEqual(['/tmp'], pkg.__path__)
        self.assertEqual(pkg_name, pkg.__name__)

    def test_create_subpackage_path_list(self):
        path_list = ['/tmp']
        pkg_name = 'heat.engine.test_path_list'
        self.assertNotIn(pkg_name, sys.modules)
        pkg = plugin_loader.create_subpackage('/tmp',
                                              'heat.engine',
                                              'test_path_list')
        self.assertIn(pkg_name, sys.modules)
        self.assertEqual(sys.modules[pkg_name], pkg)
        self.assertEqual(path_list, pkg.__path__)
        self.assertNotIn(pkg.__path__, path_list)
        self.assertEqual(pkg_name, pkg.__name__)

    def test_import_module_existing(self):
        import heat.engine.service
        existing = heat.engine.service
        importer = pkgutil.ImpImporter(heat.engine.__path__[0])
        loaded = plugin_loader._import_module(importer,
                                              'heat.engine.service',
                                              heat.engine)
        self.assertIs(existing, loaded)

    def test_import_module_garbage(self):
        importer = pkgutil.ImpImporter(heat.engine.__path__[0])
        self.assertIsNone(plugin_loader._import_module(importer,
                                                       'wibble',
                                                       heat.engine))

    @mock.patch.object(plugin_loader, "_import_module", mock.MagicMock())
    @mock.patch('pkgutil.walk_packages')
    def test_load_modules_skip_test(self, mp):
        importer = pkgutil.ImpImporter(heat.engine.__path__[0])

        mp.return_value = ((importer, "hola.foo", None),
                           (importer, "hola.tests.test_foo", None))
        loaded = plugin_loader.load_modules(
            heat.engine, ignore_error=True)
        self.assertEqual(1, len(list(loaded)))

    @mock.patch.object(plugin_loader, "_import_module", mock.MagicMock())
    @mock.patch('pkgutil.walk_packages')
    def test_load_modules_skip_setup(self, mp):
        importer = pkgutil.ImpImporter(heat.engine.__path__[0])

        mp.return_value = ((importer, "hola.foo", None),
                           (importer, "hola.setup", None))
        loaded = plugin_loader.load_modules(
            heat.engine, ignore_error=True)
        self.assertEqual(1, len(list(loaded)))
