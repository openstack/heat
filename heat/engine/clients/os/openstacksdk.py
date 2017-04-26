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

from openstack import connection
from openstack import exceptions
from openstack import profile

from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'openstack'


class OpenStackSDKPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [NETWORK] = ['network']
    service_client_map = {NETWORK: 'neutron'}
    api_version_map = {NETWORK: '2.0'}

    def _create(self, version=None):
        prof = profile.Profile()
        for svc_type in self.service_types:
            interface = self._get_client_option(
                self.service_client_map[svc_type], 'endpoint_type')
            prof.set_interface(svc_type, interface)
            prof.set_region(svc_type, self._get_region_name())
            prof.set_version(svc_type, self.api_version_map[svc_type])

        key_session = self.context.keystone_session
        return connection.Connection(authenticator=key_session.auth,
                                     verify=key_session.verify,
                                     cert=key_session.cert,
                                     profile=prof)

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.ResourceNotFound)

    def find_network_segment(self, value):
        return self.client().network.find_segment(value).id


class SegmentConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.ResourceNotFound,
                           exceptions.DuplicateResource)

    def validate_with_client(self, client, value):
        sdk_plugin = client.client_plugin(CLIENT_NAME)
        sdk_plugin.find_network_segment(value)
