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

"""Utilities to dynamically load plugin modules.

Modules imported this way remain accessible to static imports, regardless of
the order in which they are imported. For modules that are not part of an
existing package tree, use create_subpackage() to dynamically create a package
for them before loading them.
"""

import pkgutil
import sys
import types

from oslo_log import log as logging
import six


LOG = logging.getLogger(__name__)


def _module_name(*components):
    """Assemble a fully-qualified module name from its components."""
    return '.'.join(components)


def create_subpackage(path, parent_package_name, subpackage_name="plugins"):
    """Dynamically create a package into which to load plugins.

    This allows us to not include an __init__.py in the plugins directory. We
    must still create a package for plugins to go in, otherwise we get warning
    messages during import. This also provides a convenient place to store the
    path(s) to the plugins directory.
    """
    package_name = _module_name(parent_package_name, subpackage_name)

    package = types.ModuleType(package_name)
    package.__path__ = ([path] if isinstance(path, six.string_types)
                        else list(path))
    sys.modules[package_name] = package

    return package


def _import_module(importer, module_name, package):
    """Import a module dynamically into a package.

    :param importer: PEP302 Importer object (which knows the path to look in).
    :param module_name: the name of the module to import.
    :param package: the package to import the module into.
    """

    # Duplicate copies of modules are bad, so check if this has already been
    # imported statically
    if module_name in sys.modules:
        return sys.modules[module_name]

    loader = importer.find_module(module_name)
    if loader is None:
        return None

    module = loader.load_module(module_name)

    # Make this accessible through the parent package for static imports
    local_name = module_name.partition(package.__name__ + '.')[2]
    module_components = local_name.split('.')
    parent = six.moves.reduce(getattr, module_components[:-1], package)
    setattr(parent, module_components[-1], module)

    return module


def load_modules(package, ignore_error=False):
    """Dynamically load all modules from a given package."""
    path = package.__path__
    pkg_prefix = package.__name__ + '.'

    for importer, module_name, is_package in pkgutil.walk_packages(path,
                                                                   pkg_prefix):
        # Skips tests or setup packages so as not to load tests in general
        # or setup.py during doc generation.
        if '.tests.' in module_name or module_name.endswith('.setup'):
            continue

        try:
            module = _import_module(importer, module_name, package)
        except ImportError:
            LOG.error('Failed to import module %s', module_name)
            if not ignore_error:
                raise
        else:
            if module is not None:
                yield module
