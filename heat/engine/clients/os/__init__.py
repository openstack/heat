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

import abc

import six

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


@six.add_metaclass(abc.ABCMeta)
class ExtensionMixin(object):
    def __init__(self, *args, **kwargs):
        super(ExtensionMixin, self).__init__(*args, **kwargs)
        self._extensions = None

    @abc.abstractmethod
    def _list_extensions(self):
        return []

    def has_extension(self, alias):
        """Check if specific extension is present."""
        if self._extensions is None:
            self._extensions = set(self._list_extensions())
        return alias in self._extensions
