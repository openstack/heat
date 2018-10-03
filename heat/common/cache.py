#
# Copyright 2015 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The code related to integration between oslo.cache module and heat."""

from oslo_cache import core
from oslo_config import cfg

from heat.common.i18n import _


def register_cache_configurations(conf):
    """Register all configurations required for oslo.cache.

    The procedure registers all configurations required for oslo.cache.
    It should be called before configuring of cache region

    :param conf: instance of heat configuration
    :returns: updated heat configuration
    """
    # register global configurations for caching in heat
    core.configure(conf)

    # register heat specific configurations
    constraint_cache_group = cfg.OptGroup('constraint_validation_cache')
    constraint_cache_opts = [
        cfg.IntOpt('expiration_time', default=60,
                   help=_(
                       'TTL, in seconds, for any cached item in the '
                       'dogpile.cache region used for caching of validation '
                       'constraints.')),
        cfg.BoolOpt("caching", default=True,
                    help=_(
                        'Toggle to enable/disable caching when Orchestration '
                        'Engine validates property constraints of stack. '
                        'During property validation with constraints '
                        'Orchestration Engine caches requests to other '
                        'OpenStack services. Please note that the global '
                        'toggle for oslo.cache(enabled=True in [cache] group) '
                        'must be enabled to use this feature.'))
    ]
    conf.register_group(constraint_cache_group)
    conf.register_opts(constraint_cache_opts, group=constraint_cache_group)

    extension_cache_group = cfg.OptGroup('service_extension_cache')
    extension_cache_opts = [
        cfg.IntOpt('expiration_time', default=3600,
                   help=_(
                       'TTL, in seconds, for any cached item in the '
                       'dogpile.cache region used for caching of service '
                       'extensions.')),
        cfg.BoolOpt('caching', default=True,
                    help=_(
                        'Toggle to enable/disable caching when Orchestration '
                        'Engine retrieves extensions from other OpenStack '
                        'services. Please note that the global toggle for '
                        'oslo.cache(enabled=True in [cache] group) must be '
                        'enabled to use this feature.'))
    ]
    conf.register_group(extension_cache_group)
    conf.register_opts(extension_cache_opts, group=extension_cache_group)

    find_cache_group = cfg.OptGroup('resource_finder_cache')
    find_cache_opts = [
        cfg.IntOpt('expiration_time', default=3600,
                   help=_(
                       'TTL, in seconds, for any cached item in the '
                       'dogpile.cache region used for caching of OpenStack '
                       'service finder functions.')),
        cfg.BoolOpt('caching', default=True,
                    help=_(
                        'Toggle to enable/disable caching when Orchestration '
                        'Engine looks for other OpenStack service resources '
                        'using name or id. Please note that the global '
                        'toggle for oslo.cache(enabled=True in [cache] group) '
                        'must be enabled to use this feature.'))
    ]
    conf.register_group(find_cache_group)
    conf.register_opts(find_cache_opts, group=find_cache_group)

    return conf


# variable that stores an initialized cache region for heat
_REGION = None


def get_cache_region():
    global _REGION
    if not _REGION:
        _REGION = core.configure_cache_region(
            conf=register_cache_configurations(cfg.CONF),
            region=core.create_region())
    return _REGION
