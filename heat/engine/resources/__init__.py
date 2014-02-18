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

import glob
import itertools
import os
import os.path

from oslo.config import cfg

from heat.common import environment_format
from heat.openstack.common import log
from heat.openstack.common.gettextutils import _
from heat.engine import environment


LOG = log.getLogger(__name__)


def _register_resources(env, type_pairs):
    for res_name, res_class in type_pairs:
        env.register_class(res_name, res_class)


def _register_constraints(env, type_pairs):
    for constraint_name, constraint in type_pairs:
        env.register_constraint(constraint_name, constraint)


def _get_all_module_resources(module):
    '''Returns all resource in `module`.'''
    if callable(getattr(module, 'resource_mapping', None)):
        try:
            return module.resource_mapping().iteritems()
        except Exception:
            LOG.info(_('Failed to list resources from %s') % str(module))
    else:
        return {}


def _get_available_module_resources(module):
    '''
    Returns resources in `module` available for registration

    Sometimes resources should not be available for registration in Heat due to
    unsatisfied dependencies.  This function will look for a function called
    `available_resource_mapping` and, if present, return the resources the can
    be properly loaded. If this is not present, it'll look for the regular
    `resource_mapping` and return all resources from there.
    '''
    try:
        if callable(getattr(module, 'available_resource_mapping', None)):
            return module.available_resource_mapping().iteritems()
        elif callable(getattr(module, 'resource_mapping', None)):
            return module.resource_mapping().iteritems()
    except Exception:
        LOG.error(_('Failed to load resources from %s') % str(module))

    return {}


def _get_module_constraints(module):
    if callable(getattr(module, 'constraint_mapping', None)):
        return module.constraint_mapping().iteritems()
    else:
        return []


def _register_modules(env, modules):
    data_lists = [(_get_available_module_resources(m),
                   _get_module_constraints(m))
                  for m in modules]

    if data_lists:
        resource_lists, constraint_lists = zip(*data_lists)
        _register_resources(env, itertools.chain.from_iterable(resource_lists))
        _register_constraints(
            env, itertools.chain.from_iterable(constraint_lists))


_environment = None


def global_env():
    global _environment
    if _environment is None:
        initialise()
    return _environment


def _list_environment_files(env_dir):
    try:
        return glob.glob(os.path.join(env_dir, '*'))
    except OSError as osex:
        LOG.error(_('Failed to read %s') % env_dir)
        LOG.exception(osex)
        return []


def _load_all(env):
    _load_global_resources(env)
    _load_global_environment(env)


def _load_global_environment(env, env_dir=None):
    if env_dir is None:
        cfg.CONF.import_opt('environment_dir', 'heat.common.config')
        env_dir = cfg.CONF.environment_dir

    for file_path in _list_environment_files(env_dir):
        try:
            with open(file_path) as env_fd:
                LOG.info(_('Loading %s') % file_path)
                env_body = environment_format.parse(env_fd.read())
                environment_format.default_for_missing(env_body)
                env.load(env_body)
        except ValueError as vex:
            LOG.error(_('Failed to parse %(file_path)s') % {
                      'file_path': file_path})
            LOG.exception(vex)
        except IOError as ioex:
            LOG.error(_('Failed to read %(file_path)s') % {
                      'file_path': file_path})
            LOG.exception(ioex)


def initialise():
    global _environment
    if _environment is not None:
        return

    _environment = environment.Environment({}, user_env=False)
    _load_all(_environment)


def _global_modules():
    '''
    Returns all core and plugin resource modules in Heat.

    Core resource modules are yielded first to allow plugin modules to
    override them if desired.
    '''
    import sys
    from heat.common import plugin_loader

    cfg.CONF.import_opt('plugin_dirs', 'heat.common.config')
    plugin_pkg = plugin_loader.create_subpackage(cfg.CONF.plugin_dirs,
                                                 'heat.engine')

    yield __name__, plugin_loader.load_modules(sys.modules[__name__])
    yield plugin_pkg.__name__, plugin_loader.load_modules(plugin_pkg, True)


def _load_global_resources(env):
    for package, modules in _global_modules():
        _register_modules(env, modules)
