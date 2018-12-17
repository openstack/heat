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

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.octavia import octavia_base
from heat.engine import translation


class LoadBalancer(octavia_base.OctaviaBase):
    """A resource for creating octavia Load Balancers.

    This resource creates and manages octavia Load Balancers,
    which allows traffic to be directed between servers.
    """

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
        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.VIP_SUBNET],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='subnet'
            ),
        ]

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items()
                     if v is not None)
        if self.NAME not in props:
            props[self.NAME] = self.physical_resource_name()
        props['vip_subnet_id'] = props.pop(self.VIP_SUBNET)
        if 'tenant_id' in props:
            props['project_id'] = props.pop('tenant_id')
        return props

    def handle_create(self):
        properties = self._prepare_args(self.properties)
        lb = self.client().load_balancer_create(
            json={'loadbalancer': properties})['loadbalancer']
        self.resource_id_set(lb['id'])

    def check_create_complete(self, data):
        return self._check_status()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().load_balancer_set(
                self.resource_id,
                json={'loadbalancer': prop_diff})
        return prop_diff

    def check_update_complete(self, prop_diff):
        if prop_diff:
            return self._check_status()
        return True

    def _resource_delete(self):
        self.client().load_balancer_delete(self.resource_id)

    def _show_resource(self):
        return self.client().load_balancer_show(
            self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::LoadBalancer': LoadBalancer
    }
