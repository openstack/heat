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

from oslo_cache import core
from oslo_config import cfg

from heat.common import cache

MEMOIZE_EXTENSIONS = core.get_memoization_decorator(
    conf=cfg.CONF,
    region=cache.get_cache_region(),
    group="service_extension_cache")

MEMOIZE_FINDER = core.get_memoization_decorator(
    conf=cfg.CONF,
    region=cache.get_cache_region(),
    group="resource_finder_cache")
