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

from heat.engine import clients
from heat.common import exception
from heat.openstack.common import log as logging
from heat.engine import resource


if clients.neutronclient is not None:
    import neutronclient.common.exceptions as neutron_exp

logger = logging.getLogger(__name__)

class endpoint_group_selector(resource.Resource):
    tags_schema = {'Key': {'Type': 'String',
                           'Required': True},
                   'Value': {'Type': 'String',
                             'Required': True}}

    properties_schema = {
        'tenant_id': {
            'Type': 'String',
            'Required': False},
        'name': {
            'Type': 'String',
            'Required': False},
        'description': {
            'Type': 'String',
            'Required': False},
        'scope': {
            'Type': 'String',
            'Required': False},
        'value': {
            'Type': 'String',
            'Required': False}
      }


    def __init__(self, name, json_snippet, stack):
        super(endpoint, self).__init__(name, json_snippet, stack)

    def handle_create(self):
        client = self.neutron()

        props = {}
        for key in self.properties:
            if self.properties.get(key) is not None:
                props[key] = self.properties.get(key)

        egs = client.create_endpoint_group_selector({'endpoint_group_selector': props})['endpoint_group_selector']

        self.resource_id_set(egs['id'])

    def handle_delete(self):

        client = self.neutron()
        egs_id = self.resource_id

        try:
            client.delete_endpoint_group_selector(egs_id)
        except neutron_exp.NeutronClientException as ex:
            self._handle_not_found_exception(ex)

    def handle_update(self, json_snippet):
        return self.UPDATE_REPLACE


def resource_mapping():

    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::endpoint_group_selector': endpoint_group_selector,
     }

