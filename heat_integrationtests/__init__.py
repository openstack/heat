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

import os
import unittest

from heat_integrationtests.common import config

from oslo_log import log as logging

LOG = logging.getLogger(__name__, project=__name__)


def load_tests(loader, standard_tests, pattern):
    logging.setup(config.init_conf(), __name__)

    suite = unittest.TestSuite()

    heat_integration_dir = os.path.dirname(os.path.abspath(__file__))
    top_level_dir = os.path.split(heat_integration_dir)[0]
    if pattern:
        discovered = loader.discover(heat_integration_dir, pattern=pattern,
                                     top_level_dir=top_level_dir)
    else:
        discovered = loader.discover(heat_integration_dir,
                                     top_level_dir=top_level_dir)
    suite.addTests(discovered)

    # Discover tests from the heat-tempest-plugin if it is present, using
    # the Tempest plugin mechanism so we don't need a hard dependency on it.
    from tempest.test_discover import plugins as tempest_plugins

    ext_plugins = tempest_plugins.TempestTestPluginManager()
    plugin_data = ext_plugins.get_plugin_load_tests_tuple()
    heat_plugin_data = plugin_data.get('heat')
    if heat_plugin_data is not None:
        plugin_dir, plugin_path = heat_plugin_data
        LOG.info('Found Heat Tempest plugin: %s, %s', plugin_dir, plugin_path)
        if pattern:
            discovered = loader.discover(plugin_dir, pattern=pattern,
                                         top_level_dir=plugin_path)
        else:
            discovered = loader.discover(plugin_dir,
                                         top_level_dir=plugin_path)
        suite.addTests(discovered)
    else:
        LOG.error('Heat Tempest plugin not found')
        LOG.info('Available Tempest plugins: %s',
                 ', '.join(plugin_data.keys()))

    return suite
