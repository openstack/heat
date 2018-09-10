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

from oslo_config import cfg
import tenacity
from zunclient import client as zun_client
from zunclient import exceptions as zc_exc

from heat.engine.clients import client_plugin

CLIENT_NAME = 'zun'


class ZunClientPlugin(client_plugin.ClientPlugin):

    service_types = [CONTAINER] = ['container']

    default_version = '1.12'

    supported_versions = [
        V1_12, V1_18
    ] = [
        '1.12', '1.18'
    ]

    def _create(self, version=None):
        if not version:
            version = self.default_version

        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'interface': interface,
            'service_type': self.CONTAINER,
            'session': self.context.keystone_session,
            'region_name': self._get_region_name()
        }

        client = zun_client.Client(version, **args)
        return client

    def update_container(self, container_id, **prop_diff):
        if prop_diff:
            self.client(version=self.V1_18).containers.update(
                container_id, **prop_diff)

    def network_detach(self, container_id, port_id):
        with self.ignore_not_found:
            self.client(version=self.V1_18).containers.network_detach(
                container_id, port=port_id)
            return True

    def network_attach(self, container_id, port_id=None, net_id=None, fip=None,
                       security_groups=None):
        with self.ignore_not_found:
            kwargs = {}
            if port_id:
                kwargs['port'] = port_id
            if net_id:
                kwargs['network'] = net_id
            if fip:
                kwargs['fixed_ip'] = fip
            self.client(version=self.V1_18).containers.network_attach(
                container_id, **kwargs)
            return True

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(
            cfg.CONF.max_interface_check_attempts),
        wait=tenacity.wait_exponential(multiplier=0.5, max=12.0),
        retry=tenacity.retry_if_result(client_plugin.retry_if_result_is_false))
    def check_network_detach(self, container_id, port_id):
        with self.ignore_not_found:
            interfaces = self.client(
                version=self.V1_18).containers.network_list(container_id)
            for iface in interfaces:
                if iface.port_id == port_id:
                    return False
        return True

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(
            cfg.CONF.max_interface_check_attempts),
        wait=tenacity.wait_exponential(multiplier=0.5, max=12.0),
        retry=tenacity.retry_if_result(client_plugin.retry_if_result_is_false))
    def check_network_attach(self, container_id, port_id):
        if not port_id:
            return True

        interfaces = self.client(version=self.V1_18).containers.network_list(
            container_id)
        for iface in interfaces:
            if iface.port_id == port_id:
                return True
        return False

    def is_not_found(self, ex):
        return isinstance(ex, zc_exc.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, zc_exc.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, zc_exc.Conflict)
