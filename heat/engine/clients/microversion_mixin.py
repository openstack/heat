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

from heat.common import exception


@six.add_metaclass(abc.ABCMeta)
class MicroversionMixin(object):
    """Mixin For microversion support."""

    def client(self, version=None):
        if version is None:
            version = self.get_max_microversion()
        elif not self.is_version_supported(version):
            raise exception.InvalidServiceVersion(
                version=version,
                service=self._get_service_name())

        if version in self._client_instances:
            return self._client_instances[version]

        self._client_instances[version] = self._create(version=version)
        return self._client_instances[version]

    @abc.abstractmethod
    def get_max_microversion(self):
        pass

    @abc.abstractmethod
    def is_version_supported(self, version):
        pass
