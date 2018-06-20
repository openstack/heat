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

from openstack.config import cloud_region
from openstack import connection
from openstack import exceptions
import os_service_types

from heat.common import config
from heat.engine.clients import client_plugin
from heat.engine import constraints
import heat.version

CLIENT_NAME = 'openstack'


class OpenStackSDKPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [NETWORK, CLUSTERING] = ['network', 'clustering']

    def _create(self, version=None):
        config = cloud_region.from_session(
            # TODO(mordred) The way from_session calculates a cloud name
            # doesn't interact well with the mocks in the test cases. The
            # name is used in logging to distinguish requests made to different
            # clouds. For now, set it to local - but maybe find a way to set
            # it to something more meaningful later.
            name='local',
            session=self.context.keystone_session,
            config=self._get_service_interfaces(),
            region_name=self._get_region_name(),
            app_name='heat',
            app_version=heat.version.version_info.version_string(),
            **self._get_additional_create_args(version))
        return connection.Connection(config=config)

    def _get_additional_create_args(self, version):
        return {}

    def _get_service_interfaces(self):
        interfaces = {}
        if not os_service_types:
            return interfaces
        types = os_service_types.ServiceTypes()
        for name, _ in config.list_opts():
            if not name or not name.startswith('clients_'):
                continue
            project_name = name.split("_", 1)[0]
            service_data = types.get_service_data_for_project(project_name)
            if not service_data:
                continue
            service_type = service_data['service_type']
            interfaces[service_type + '_interface'] = self._get_client_option(
                service_type, 'endpoint_type')
        return interfaces

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFoundException)

    def find_network_segment(self, value):
        return self.client().network.find_segment(value).id


class SegmentConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.ResourceNotFound,
                           exceptions.DuplicateResource)

    def validate_with_client(self, client, value):
        sdk_plugin = client.client_plugin(CLIENT_NAME)
        sdk_plugin.find_network_segment(value)
