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
from heat.engine.resources.neutron import neutron
from heat.engine import scheduler

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class VPNService(neutron.NeutronResource):
    """
    A resource for VPN service in Neutron.
    """

    properties_schema = {'name': {'Type': 'String'},
                         'description': {'Type': 'String'},
                         'admin_state_up': {'Type': 'Boolean',
                                            'Default': True},
                         'subnet_id': {'Type': 'String',
                                       'Required': True},
                         'router_id': {'Type': 'String',
                                       'Required': True}}

    attributes_schema = {
        'admin_state_up': 'the administrative state of the vpn service',
        'description': 'description of the vpn service',
        'id': 'unique identifier for the vpn service',
        'name': 'name for the vpn service',
        'router_id': 'unique identifier for router used to create the vpn'
                     ' service',
        'status': 'the status of the vpn service',
        'subnet_id': 'unique identifier for subnet used to create the vpn'
                     ' service',
        'tenant_id': 'tenant owning the vpn service'
    }

    update_allowed_keys = ('Properties',)

    update_allowed_properties = ('name', 'description', 'admin_state_up',)

    def _show_resource(self):
        return self.neutron().show_vpnservice(self.resource_id)['vpnservice']

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        vpnservice = self.neutron().create_vpnservice({'vpnservice': props})[
            'vpnservice']
        self.resource_id_set(vpnservice['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_vpnservice(self.resource_id,
                                             {'vpnservice': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_vpnservice(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::VPNService': VPNService,
    }
