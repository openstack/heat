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

import collections
import itertools
import sys

from oslo_config import cfg
from oslo_log import log
import six

from heat.common import plugin_loader

LOG = log.getLogger(__name__)


class PluginManager(object):
    """A class for managing plugin modules."""

    def __init__(self, *extra_packages):
        """Initialise the Heat Engine plugin package, and any others.

        The heat.engine.plugins package is always created, if it does not
        exist, from the plugin directories specified in the config file, and
        searched for modules. In addition, any extra packages specified are
        also searched for modules. e.g.

        >>> PluginManager('heat.engine.resources')

        will load all modules in the heat.engine.resources package as well as
        any user-supplied plugin modules.
        """
        def packages():
            for package_name in extra_packages:
                yield sys.modules[package_name]

            cfg.CONF.import_opt('plugin_dirs', 'heat.common.config')
            yield plugin_loader.create_subpackage(cfg.CONF.plugin_dirs,
                                                  'heat.engine')

        def modules():
            pkg_modules = six.moves.map(plugin_loader.load_modules,
                                        packages())
            return itertools.chain.from_iterable(pkg_modules)

        self.modules = list(modules())

    def map_to_modules(self, function):
        """Iterate over the results of calling a function on every module."""
        return six.moves.map(function, self.modules)


class PluginMapping(object):
    """A class for managing plugin mappings."""

    def __init__(self, names, *args, **kwargs):
        """Initialise with the mapping name(s) and arguments.

        `names` can be a single name or a list of names. The first name found
        in a given module is the one used. Each module is searched for a
        function called <name>_mapping() which is called to retrieve the
        mappings provided by that module. Any other arguments passed will be
        passed to the mapping functions.
        """
        if isinstance(names, six.string_types):
            names = [names]

        self.names = ['%s_mapping' % name for name in names]
        self.args = args
        self.kwargs = kwargs

    def load_from_module(self, module):
        """Return the mapping specified in the given module.

        If no such mapping is specified, an empty dictionary is returned.
        """
        for mapping_name in self.names:
            mapping_func = getattr(module, mapping_name, None)
            if callable(mapping_func):
                fmt_data = {'mapping_name': mapping_name, 'module': module}
                try:
                    mapping_dict = mapping_func(*self.args, **self.kwargs)
                except Exception:
                    LOG.error('Failed to load %(mapping_name)s '
                              'from %(module)s', fmt_data)
                    raise
                else:
                    if isinstance(mapping_dict, collections.Mapping):
                        return mapping_dict
                    elif mapping_dict is not None:
                        LOG.error('Invalid type for %(mapping_name)s '
                                  'from %(module)s', fmt_data)

        return {}

    def load_all(self, plugin_manager):
        """Iterate over the mappings from all modules in the plugin manager.

        Mappings are returned as a list of (key, value) tuples.
        """
        mod_dicts = plugin_manager.map_to_modules(self.load_from_module)
        return itertools.chain.from_iterable(six.iteritems(d) for d
                                             in mod_dicts)
