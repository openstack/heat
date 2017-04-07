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

from magnumclient import exceptions as mc_exc
from magnumclient.v1 import client as magnum_client

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'magnum'


class MagnumClientPlugin(client_plugin.ClientPlugin):

    service_types = [CONTAINER] = ['container-infra']

    def _create(self):
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'interface': interface,
            'service_type': self.CONTAINER,
            'session': self.context.keystone_session,
            'region_name': self._get_region_name()
        }
        client = magnum_client.Client(**args)
        return client

    def is_not_found(self, ex):
        return isinstance(ex, mc_exc.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, mc_exc.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, mc_exc.Conflict)

    def _get_rsrc_name_or_id(self, value, entity, entity_msg):
        entity_client = getattr(self.client(), entity)
        try:
            return entity_client.get(value).uuid
        except mc_exc.NotFound:
            # Magnum cli will find the value either is name or id,
            # so no need to call list() here.
            raise exception.EntityNotFound(entity=entity_msg,
                                           name=value)

    def get_baymodel(self, value):
        return self._get_rsrc_name_or_id(value, entity='baymodels',
                                         entity_msg='BayModel')

    def get_cluster_template(self, value):
        return self._get_rsrc_name_or_id(value, entity='cluster_templates',
                                         entity_msg='ClusterTemplate')


class ClusterTemplateConstraint(constraints.BaseCustomConstraint):

    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_cluster_template'


class BaymodelConstraint(constraints.BaseCustomConstraint):

    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_baymodel'
