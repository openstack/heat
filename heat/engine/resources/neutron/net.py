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
    from neutronclient.common.exceptions import NeutronClientException

logger = logging.getLogger(__name__)


class Net(neutron.NeutronResource):
    properties_schema = {
        'name': {
            'Type': 'String',
            'Description': _('A string specifying a symbolic name for '
                             'the network, which is not required to be '
                             'unique.')
        },
        'value_specs': {
            'Type': 'Map',
            'Default': {},
            'Description': _('Extra parameters to include in the "network" '
                             'object in the creation request. Parameters '
                             'are often specific to installed hardware or '
                             'extensions.')
        },
        'admin_state_up': {
            'Default': True,
            'Type': 'Boolean',
            'Description': _('A boolean value specifying the administrative '
                             'status of the network.')
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
                             'administrative users only.')
        }}
    attributes_schema = {
        "status": _("The status of the network."),
        "name": _("The name of the network."),
        "subnets": _("Subnets of this network."),
        "admin_state_up": _("The administrative status of the network."),
        "tenant_id": _("The tenant owning this network."),
    }

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
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Net': Net,
    }
