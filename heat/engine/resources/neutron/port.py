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


class Port(neutron.NeutronResource):

    fixed_ip_schema = {'subnet_id': {'Type': 'String'},
                       'ip_address': {'Type': 'String'}}

    properties_schema = {
        'network_id': {
            'Type': 'String',
            'Required': True
        },
        'name': {
            'Type': 'String'
        },
        'value_specs': {
            'Type': 'Map',
            'Default': {},
        },
        'admin_state_up': {
            'Default': True,
            'Type': 'Boolean',
            'UpdateAllowed': True
        },
        'fixed_ips': {
            'Type': 'List',
            'Default': [],
            'UpdateAllowed': True,
            'Schema': {
                'Type': 'Map',
                'Schema': fixed_ip_schema
            }
        },
        'mac_address': {
            'Type': 'String'
        },
        'device_id': {
            'Type': 'String'
        },
        'security_groups': {
            'Type': 'List',
            'UpdateAllowed': True,
            'Default': [],
        }
    }
    attributes_schema = {
        "admin_state_up": _("The administrative state of this port."),
        "device_id": _("Unique identifier for the device."),
        "device_owner": _("Name of the network owning the port."),
        "fixed_ips": _("Fixed ip addresses."),
        "mac_address": _("Mac address of the port."),
        "name": _("Friendly name of the port."),
        "network_id": _("Unique identifier for the network owning the port."),
        "security_groups": _("A list of security groups for the port."),
        "status": _("The status of the port."),
        "tenant_id": _("Tenant owning the port."),
        "show": _("All attributes."),
    }

    update_allowed_keys = ('Properties',)

    def add_dependencies(self, deps):
        super(Port, self).add_dependencies(deps)
        # Depend on any Subnet in this template with the same
        # network_id as this network_id.
        # It is not known which subnet a port might be assigned
        # to so all subnets in a network should be created before
        # the ports in that network.
        for resource in self.stack.itervalues():
            if (resource.has_interface('OS::Neutron::Subnet') and
                resource.properties.get('network_id') ==
                    self.properties.get('network_id')):
                        deps += (self, resource)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        self._prepare_list_properties(props)

        port = self.neutron().create_port({'port': props})['port']
        self.resource_id_set(port['id'])

    def _prepare_list_properties(self, props):
        for fixed_ip in props.get('fixed_ips', []):
            for key, value in fixed_ip.items():
                if value is None:
                    fixed_ip.pop(key)

        if props.get('security_groups'):
            props['security_groups'] = self.get_secgroup_uuids(
                self.stack, props, 'security_groups', props.get('name'),
                self.neutron())

    def _show_resource(self):
        return self.neutron().show_port(
            self.resource_id)['port']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_port(self.resource_id)
        except neutron_exp.NeutronClientException as ex:
            self._handle_not_found_exception(ex)
        else:
            return scheduler.TaskRunner(self._confirm_delete)()

    def _handle_not_found_exception(self, ex):
        # raise any exception which is not for a not found port
        if not (ex.status_code == 404 or
                isinstance(ex, neutron_exp.PortNotFoundClient)):
            raise ex

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)

        self._prepare_list_properties(props)

        logger.debug('updating port with %s' % props)
        self.neutron().update_port(self.resource_id, {'port': props})

    def check_update_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Port': Port,
    }
