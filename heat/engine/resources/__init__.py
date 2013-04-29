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
from heat.openstack.common import log as logging


logger = logging.getLogger(__name__)


def _register_resources(type_pairs):
    from heat.engine import resource

    for res_name, res_class in type_pairs:
        resource._register_class(res_name, res_class)


def _get_module_resources(module):
    if callable(getattr(module, 'resource_mapping', None)):
        try:
            return module.resource_mapping().iteritems()
        except Exception as ex:
            logger.error(_('Failed to load resources from %s') % str(module))
    else:
        return []


def _register_modules(modules):
    import itertools

    resource_lists = (_get_module_resources(m) for m in modules)
    _register_resources(itertools.chain.from_iterable(resource_lists))


_initialized = False


def initialise():
    global _initialized
    if _initialized:
        return
    import sys
    from heat.common import config
    from heat.common import plugin_loader

    config.register_engine_opts()

    _register_modules(plugin_loader.load_modules(sys.modules[__name__]))

    from oslo.config import cfg

    plugin_pkg = plugin_loader.create_subpackage(cfg.CONF.plugin_dirs,
                                                 'heat.engine')
    _register_modules(plugin_loader.load_modules(plugin_pkg, True))
    _initialized = True
