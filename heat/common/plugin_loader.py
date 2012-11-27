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

import pkgutil
import sys
import types

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


def _module_name(*components):
    return '.'.join(components)


def create_subpackage(path, parent_package_name, subpackage_name="plugins"):
    package_name = _module_name(parent_package_name, subpackage_name)

    package = types.ModuleType(package_name)
    package.__path__ = [path] if isinstance(path, basestring) else list(path)
    sys.modules[package_name] = package

    return package


def _import_module(importer, module_name, package):
    fullname = _module_name(package.__name__, module_name)
    if fullname in sys.modules:
        return sys.modules[fullname]

    loader = importer.find_module(fullname)
    if loader is None:
        return None

    module = loader.load_module(fullname)
    setattr(package, module_name, module)
    return module


def load_modules(package, ignore_error=False):
    path = package.__path__
    for importer, module_name, is_package in pkgutil.walk_packages(path):
        try:
            module = _import_module(importer, module_name, package)
        except ImportError as ex:
            logger.error(_('Failed to import module %s') % module_name)
            if not ignore_error:
                raise
        else:
            if module is not None:
                yield module
