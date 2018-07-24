#
#    Copyright 2015 IBM Corp.
#
#    All Rights Reserved.
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

from neutronclient.common import exceptions

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class LoadBalancer(neutron.NeutronResource):
    """A resource for creating LBaaS v2 Load Balancers.

    This resource creates and manages Neutron LBaaS v2 Load Balancers,
    which allows traffic to be directed between servers.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'lbaasv2'

    entity = 'loadbalancer'

    PROPERTIES = (
        DESCRIPTION, NAME, PROVIDER, VIP_ADDRESS, VIP_SUBNET,
        ADMIN_STATE_UP, TENANT_ID
    ) = (
        'description', 'name', 'provider', 'vip_address', 'vip_subnet',
        'admin_state_up', 'tenant_id'
    )

    ATTRIBUTES = (
        VIP_ADDRESS_ATTR, VIP_PORT_ATTR, VIP_SUBNET_ATTR, POOLS_ATTR
    ) = (
        'vip_address', 'vip_port_id', 'vip_subnet_id', 'pools'
    )

    properties_schema = {
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of this Load Balancer.'),
            update_allowed=True,
            default=''
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of this Load Balancer.'),
            update_allowed=True
        ),
        PROVIDER: properties.Schema(
            properties.Schema.STRING,
            _('Provider for this Load Balancer.'),
            constraints=[
                constraints.CustomConstraint('neutron.lbaas.provider')
            ],
        ),
        VIP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('IP address for the VIP.'),
            constraints=[
                constraints.CustomConstraint('ip_addr')
            ],
        ),
        VIP_SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('The name or ID of the subnet on which to allocate the VIP '
              'address.'),
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ],
            required=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of this Load Balancer.'),
            default=True,
            update_allowed=True
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the tenant who owns the Load Balancer. Only '
              'administrative users can specify a tenant ID other than '
              'their own.'),
            constraints=[
                constraints.CustomConstraint('keystone.project')
            ],
        )
    }

    attributes_schema = {
        VIP_ADDRESS_ATTR: attributes.Schema(
            _('The VIP address of the LoadBalancer.'),
            type=attributes.Schema.STRING
        ),
        VIP_PORT_ATTR: attributes.Schema(
            _('The VIP port of the LoadBalancer.'),
            type=attributes.Schema.STRING
        ),
        VIP_SUBNET_ATTR: attributes.Schema(
            _('The VIP subnet of the LoadBalancer.'),
            type=attributes.Schema.STRING
        ),
        POOLS_ATTR: attributes.Schema(
            _('Pools this LoadBalancer is associated with.'),
            type=attributes.Schema.LIST,
            support_status=support.SupportStatus(version='9.0.0')
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.VIP_SUBNET],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET
            ),
        ]

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name()
        )
        properties['vip_subnet_id'] = properties.pop(self.VIP_SUBNET)
        lb = self.client().create_loadbalancer(
            {'loadbalancer': properties})['loadbalancer']
        self.resource_id_set(lb['id'])

    def check_create_complete(self, data):
        return self.client_plugin().check_lb_status(self.resource_id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_loadbalancer(
                self.resource_id,
                {'loadbalancer': prop_diff})
        return prop_diff

    def check_update_complete(self, prop_diff):
        if prop_diff:
            return self.client_plugin().check_lb_status(self.resource_id)
        return True

    def handle_delete(self):
        pass

    def check_delete_complete(self, data):
        if self.resource_id is None:
            return True

        try:
            try:
                if self.client_plugin().check_lb_status(self.resource_id):
                    self.client().delete_loadbalancer(self.resource_id)
            except exception.ResourceInError:
                # Still try to delete loadbalancer in error state
                self.client().delete_loadbalancer(self.resource_id)
        except exceptions.NotFound:
            # Resource is gone
            return True

        return False


def resource_mapping():
    return {
        'OS::Neutron::LBaaS::LoadBalancer': LoadBalancer
    }
