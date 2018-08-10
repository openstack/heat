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
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.octavia import octavia_base
from heat.engine import translation


class PoolMember(octavia_base.OctaviaBase):
    """A resource for managing Octavia Pool Members.

    A pool member represents a single backend node.
    """

    PROPERTIES = (
        POOL, ADDRESS, PROTOCOL_PORT, MONITOR_ADDRESS, MONITOR_PORT,
        WEIGHT, ADMIN_STATE_UP, SUBNET,
    ) = (
        'pool', 'address', 'protocol_port', 'monitor_address', 'monitor_port',
        'weight', 'admin_state_up', 'subnet'
    )

    ATTRIBUTES = (
        ADDRESS_ATTR, POOL_ID_ATTR
    ) = (
        'address', 'pool_id'
    )

    properties_schema = {
        POOL: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of the load balancing pool.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('octavia.pool')
            ]
        ),
        ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('IP address of the pool member on the pool network.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('ip_addr')
            ]
        ),
        PROTOCOL_PORT: properties.Schema(
            properties.Schema.INTEGER,
            _('Port on which the pool member listens for requests or '
              'connections.'),
            required=True,
            constraints=[
                constraints.Range(1, 65535),
            ]
        ),
        MONITOR_ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Alternate IP address which health monitor can use for '
              'health check.'),
            constraints=[
                constraints.CustomConstraint('ip_addr')
            ]
        ),
        MONITOR_PORT: properties.Schema(
            properties.Schema.INTEGER,
            _('Alternate Port which health monitor can use for health check.'),
            constraints=[
                constraints.Range(1, 65535),
            ]
        ),
        WEIGHT: properties.Schema(
            properties.Schema.INTEGER,
            _('Weight of pool member in the pool (default to 1).'),
            default=1,
            constraints=[
                constraints.Range(0, 256),
            ],
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of the pool member.'),
            default=True,
            update_allowed=True
        ),
        SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('Subnet name or ID of this member.'),
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ],
        ),
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SUBNET],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='subnet'
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.POOL],
                client_plugin=self.client_plugin(),
                finder='get_pool'
            ),
        ]

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items() if v is not None)
        props.pop(self.POOL)
        if self.SUBNET in props:
            props['subnet_id'] = props.pop(self.SUBNET)
        return props

    def _resource_create(self, properties):
        pool = self.properties[self.POOL]
        return self.client().member_create(
            pool, json={'member': properties})['member']

    def _resource_update(self, prop_diff):
        pool = self.properties[self.POOL]
        self.client().member_set(pool,
                                 self.resource_id,
                                 json={'member': prop_diff})

    def _resource_delete(self):
        pool = self.properties[self.POOL]
        if pool:
            self.client().member_delete(pool, self.resource_id)

    def _show_resource(self):
        pool = self.properties[self.POOL]
        return self.client().member_show(pool, self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::PoolMember': PoolMember,
    }
