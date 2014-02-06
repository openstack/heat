
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
from heat.engine import properties
from heat.engine.resources.neutron import neutron

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException


class ExtraRoute(neutron.NeutronResource):

    PROPERTIES = (
        ROUTER_ID, DESTINATION, NEXTHOP,
    ) = (
        'router_id', 'destination', 'nexthop',
    )

    properties_schema = {
        ROUTER_ID: properties.Schema(
            properties.Schema.STRING,
            description=_('The router id.'),
            required=True),
        DESTINATION: properties.Schema(
            properties.Schema.STRING,
            description=_('Network in CIDR notation.'),
            required=True),
        NEXTHOP: properties.Schema(
            properties.Schema.STRING,
            description=_('Nexthop IP adddress.'),
            required=True)
    }

    def add_dependencies(self, deps):
        super(ExtraRoute, self).add_dependencies(deps)
        for resource in self.stack.itervalues():
            # depend on any RouterInterface in this template with the same
            # router_id as this router_id
            if (resource.has_interface('OS::Neutron::RouterInterface') and
                resource.properties['router_id'] ==
                    self.properties['router_id']):
                        deps += (self, resource)
            # depend on any RouterGateway in this template with the same
            # router_id as this router_id
            elif (resource.has_interface('OS::Neutron::RouterGateway') and
                  resource.properties['router_id'] ==
                    self.properties['router_id']):
                        deps += (self, resource)

    def handle_create(self):
        router_id = self.properties.get(self.ROUTER_ID)
        routes = self.neutron().show_router(
            router_id).get('router').get('routes')
        if not routes:
            routes = []
        new_route = {'destination': self.properties[self.DESTINATION],
                     'nexthop': self.properties[self.NEXTHOP]}
        if new_route in routes:
            msg = _('Route duplicates an existing route.')
            raise exception.Error(msg)
        routes.append(new_route)
        self.neutron().update_router(router_id, {'router':
                                     {'routes': routes}})
        new_route['router_id'] = router_id
        self.resource_id_set(
            '%(router_id)s:%(destination)s:%(nexthop)s' % new_route)

    def handle_delete(self):
        if not self.resource_id:
            return
        (router_id, destination, nexthop) = self.resource_id.split(':')
        try:
            routes = self.neutron().show_router(
                router_id).get('router').get('routes', [])
            try:
                routes.remove({'destination': destination,
                               'nexthop': nexthop})
            except ValueError:
                return
            self.neutron().update_router(router_id, {'router':
                                         {'routes': routes}})
        except NeutronClientException as ex:
            self._handle_not_found_exception(ex)


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::ExtraRoute': ExtraRoute,
    }
