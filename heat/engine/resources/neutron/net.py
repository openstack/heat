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
from heat.openstack.common import log as logging
from heat.engine.resources.neutron import neutron
from heat.engine import scheduler

if clients.neutronclient is not None:
    import neutronclient.common.exceptions as neutron_exp

logger = logging.getLogger(__name__)


class Net(neutron.NeutronResource):
    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _('A string specifying a symbolic name for '
                             'the network, which is not required to be '
                             'unique.'),
            'UpdateAllowed': True
        },
        'value_specs': {
            'Type': 'Map',
            'Default': {},
            'Description': _('Extra parameters to include in the "network" '
                             'object in the creation request. Parameters '
                             'are often specific to installed hardware or '
                             'extensions.'),
            'UpdateAllowed': True
        },
        'admin_state_up': {
            'Default': True,
            'Type': 'Boolean',
            'Description': _('A boolean value specifying the administrative '
                             'status of the network.'),
            'UpdateAllowed': True
        },
        'tenant_id': {
            'Type': 'String',
            'Description': _('The ID of the tenant which will own the '
                             'network. Only administrative users can set '
                             'the tenant identifier; this cannot be changed '
                             'using authorization policies.')
        },
        'shared': {
            'Type': 'Boolean',
            'Description': _('Whether this network should be shared across '
                             'all tenants. Note that the default policy '
                             'setting restricts usage of this attribute to '
                             'administrative users only.'),
            'UpdateAllowed': True,
            'Default': False
        }}
    attributes_schema = {
        "status": _("The status of the network."),
        "name": _("The name of the network."),
        "subnets": _("Subnets of this network."),
        "admin_state_up": _("The administrative status of the network."),
        "tenant_id": _("The tenant owning this network."),
        "show": _("All attributes."),
    }

    update_allowed_keys = ('Properties',)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        net = self.neutron().create_network({'network': props})['network']
        self.resource_id_set(net['id'])

    def _show_resource(self):
        return self.neutron().show_network(
            self.resource_id)['network']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_network(self.resource_id)
        except neutron_exp.NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return scheduler.TaskRunner(self._confirm_delete)()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)

        self.neutron().update_network(self.resource_id, {'network': props})

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def _handle_not_found_exception(self, ex):
        # raise any exception which is not for a not found network
        if not (ex.status_code == 404 or
                isinstance(ex, neutron_exp.NetworkNotFoundClient)):
            raise ex


class NetDHCPAgent(neutron.NeutronResource):
    properties_schema = {
        'network_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('The ID of the network you want to be scheduled '
                             'by the dhcp_agent. Note that the default policy '
                             'setting in Neutron restricts usage of this '
                             'property to administrative users only.'),
        },
        'dhcp_agent_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('The ID of the dhcp-agent to schedule '
                             'the network. Note that the default policy '
                             'setting in Neutron restricts usage of this '
                             'property to administrative users only.'),
        }
    }

    def handle_create(self):
        network_id = self.properties['network_id']
        dhcp_agent_id = self.properties['dhcp_agent_id']
        self.neutron().add_network_to_dhcp_agent(
            dhcp_agent_id, {'network_id': network_id})
        self.resource_id_set('%(net)s:%(agt)s' %
                             {'net': network_id, 'agt': dhcp_agent_id})

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()
        network_id, dhcp_agent_id = self.resource_id.split(':')
        try:
            client.remove_network_from_dhcp_agent(
                dhcp_agent_id, network_id)
        except neutron_exp.NeutronClientException as ex:
            # assume 2 patterns about status_code following:
            #  404: the network or agent is already gone
            #  409: the network isn't scheduled by the dhcp_agent
            if ex.status_code not in (404, 409):
                raise ex


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Net': Net,
        'OS::Neutron::NetDHCPAgent': NetDHCPAgent,
    }
