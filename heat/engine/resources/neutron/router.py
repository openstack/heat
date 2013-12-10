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

from heat.common import exception
from heat.engine import clients
from heat.engine.resources.neutron import neutron
from heat.engine import properties
from heat.engine import scheduler

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException
    from neutronclient.neutron import v2_0 as neutronV20

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class Router(neutron.NeutronResource):
    properties_schema = {'name': {'Type': 'String',
                                  'UpdateAllowed': True},
                         'value_specs': {'Type': 'Map',
                                         'Default': {},
                                         'UpdateAllowed': True},
                         'admin_state_up': {'Type': 'Boolean',
                                            'Default': True,
                                            'UpdateAllowed': True}}
    attributes_schema = {
        "status": _("The status of the router."),
        "external_gateway_info": _("Gateway network for the router."),
        "name": _("Friendly name of the router."),
        "admin_state_up": _("Administrative state of the router."),
        "tenant_id": _("Tenant owning the router."),
        "show": _("All attributes."),
    }

    update_allowed_keys = ('Properties',)

    def handle_create(self):
        props = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        router = self.neutron().create_router({'router': props})['router']
        self.resource_id_set(router['id'])

    def _show_resource(self):
        return self.neutron().show_router(
            self.resource_id)['router']

    def check_create_complete(self, *args):
        attributes = self._show_resource()
        return self.is_built(attributes)

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_router(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        props = self.prepare_update_properties(json_snippet)
        self.neutron().update_router(
            self.resource_id, {'router': props})


class RouterInterface(neutron.NeutronResource):
    properties_schema = {
        'router_id': {
            'Type': 'String',
            'Required': True,
            'Description': _('The router id.')},
        'subnet_id': {
            'Type': 'String',
            'Description': _('The subnet id, either '
                             'subnet_id or port_id should be specified.')},
        'port_id': {
            'Type': 'String',
            'Description': _('The port id, either '
                             'subnet_id or port_id should be specified.')}}

    def add_dependencies(self, deps):
        super(RouterInterface, self).add_dependencies(deps)
        # depend on any RouterL3agents in this template with the same router_id
        # as this router_id.
        for resource in self.stack.itervalues():
            if (resource.has_interface('OS::Neutron::RouterL3Agent') and
                resource.properties.get('router_id') ==
                    self.properties.get('router_id')):
                        deps += (self, resource)

    def validate(self):
        '''
        Validate any of the provided params
        '''
        super(RouterInterface, self).validate()
        subnet_id = self.properties.get('subnet_id')
        port_id = self.properties.get('port_id')
        if subnet_id and port_id:
            raise exception.ResourcePropertyConflict('subnet_id', 'port_id')
        if not subnet_id and not port_id:
            msg = 'Either subnet_id or port_id must be specified.'
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        router_id = self.properties.get('router_id')
        key = 'subnet_id'
        value = self.properties.get(key)
        if not value:
            key = 'port_id'
            value = self.properties.get(key)
        self.neutron().add_interface_router(
            router_id,
            {key: value})
        self.resource_id_set('%s:%s=%s' % (router_id, key, value))

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()
        tokens = self.resource_id.replace('=', ':').split(':')
        if len(tokens) == 2:    # compatible with old data
            tokens.insert(1, 'subnet_id')
        (router_id, key, value) = tokens
        try:
            client.remove_interface_router(
                router_id,
                {key: value})
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex


class RouterGateway(neutron.NeutronResource):
    properties_schema = {'router_id': {'Type': 'String',
                                       'Required': True},
                         'network_id': {'Type': 'String',
                                        'Required': True}}

    def add_dependencies(self, deps):
        super(RouterGateway, self).add_dependencies(deps)
        for resource in self.stack.itervalues():
            # depend on any RouterInterface in this template with the same
            # router_id as this router_id
            if (resource.has_interface('OS::Neutron::RouterInterface') and
                resource.properties.get('router_id') ==
                    self.properties.get('router_id')):
                        deps += (self, resource)
            # depend on any subnet in this template with the same network_id
            # as this network_id, as the gateway implicitly creates a port
            # on that subnet
            elif (resource.has_interface('OS::Neutron::Subnet') and
                  resource.properties.get('network_id') ==
                    self.properties.get('network_id')):
                        deps += (self, resource)
            # depend on any RouterL3agents in this template with the same
            # router_id as this router_id.
            elif (resource.has_interface('OS::Neutron::RouterL3Agent') and
                  resource.properties.get('router_id') ==
                    self.properties.get('router_id')):
                        deps += (self, resource)

    def handle_create(self):
        router_id = self.properties.get('router_id')
        network_id = neutronV20.find_resourceid_by_name_or_id(
            self.neutron(),
            'network',
            self.properties.get('network_id'))
        self.neutron().add_gateway_router(
            router_id,
            {'network_id': network_id})
        self.resource_id_set('%s:%s' % (router_id, network_id))

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()
        (router_id, network_id) = self.resource_id.split(':')
        try:
            client.remove_gateway_router(router_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex


class RouterL3Agent(neutron.NeutronResource):
    properties_schema = {
        'router_id': properties.Schema(
            properties.Schema.STRING,
            description=_('The ID of the router you want to be scheduled by '
                          'the l3_agent. Note that the default policy setting '
                          'in Neutron restricts usage of this property to '
                          'administrative users only.'),
            required=True
        ),
        'l3_agent_id': properties.Schema(
            properties.Schema.STRING,
            description=_('The ID of the l3-agent to schedule the router. '
                          'Note that the default policy setting in Neutron '
                          'restricts usage of this property to administrative '
                          'users only.'),
            required=True
        )
    }

    def handle_create(self):
        router_id = self.properties['router_id']
        l3_agent_id = self.properties['l3_agent_id']
        self.neutron().add_router_to_l3_agent(
            l3_agent_id, {'router_id': router_id})
        self.resource_id_set('%(rtr)s:%(agt)s' %
                             {'rtr': router_id, 'agt': l3_agent_id})

    def handle_delete(self):
        if not self.resource_id:
            return
        client = self.neutron()
        router_id, l3_agent_id = self.resource_id.split(':')
        try:
            client.remove_router_from_l3_agent(
                l3_agent_id, router_id)
        except NeutronClientException as ex:
            # assume 2 patterns about status_code following:
            #  404: the router or agent is already gone
            #  409: the router isn't scheduled by the l3_agent
            if ex.status_code not in (404, 409):
                raise ex


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::Router': Router,
        'OS::Neutron::RouterInterface': RouterInterface,
        'OS::Neutron::RouterGateway': RouterGateway,
        'OS::Neutron::RouterL3Agent': RouterL3Agent,
    }
