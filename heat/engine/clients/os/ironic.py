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

from ironicclient.common.apiclient import exceptions as ic_exc
from ironicclient.common import http
from ironicclient.v1 import client as ironic_client
from oslo_config import cfg
from oslo_utils import versionutils

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine.clients import microversion_mixin
from heat.engine import constraints

CLIENT_NAME = 'ironic'


class IronicClientPlugin(microversion_mixin.MicroversionMixin,
                         client_plugin.ClientPlugin):

    service_types = [BAREMETAL] = ['baremetal']
    # TODO(tkajinam): This should probably be detected via API, but current
    #                 ironicclient does not expose any API for it.
    IRONIC_API_VERSION = http.LATEST_VERSION
    max_microversion = cfg.CONF.max_ironic_api_microversion

    def _create(self, version=None):
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'interface': interface,
            'service_type': self.BAREMETAL,
            'session': self.context.keystone_session,
            'region_name': self._get_region_name(),
        }
        if version:
            args['os_ironic_api_version'] = version

        client = ironic_client.Client(**args)
        return client

    def is_not_found(self, ex):
        return isinstance(ex, ic_exc.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, ic_exc.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, ic_exc.Conflict)

    def _get_rsrc_name_or_id(self, value, entity, entity_msg):
        entity_client = getattr(self.client(), entity)
        try:
            return entity_client.get(value).uuid
        except ic_exc.NotFound:
            # Ironic cli will find the value either is name or id,
            # so no need to call list() here.
            raise exception.EntityNotFound(entity=entity_msg,
                                           name=value)

    def get_portgroup(self, value):
        return self._get_rsrc_name_or_id(value, entity='portgroup',
                                         entity_msg='PortGroup')

    def get_node(self, value):
        return self._get_rsrc_name_or_id(value, entity='node',
                                         entity_msg='Node')

    def get_max_microversion(self):
        if not self.max_microversion:
            self.max_microversion = self.IRONIC_API_VERSION
        return self.max_microversion

    def is_version_supported(self, version):
        return versionutils.is_compatible(version, self.get_max_microversion())


class PortGroupConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_portgroup'


class NodeConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_node'
