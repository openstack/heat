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

from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation


class PoolMember(neutron.NeutronResource):
    """A resource for managing LBaaS v2 Pool Members.

    A pool member represents a single backend node.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'lbaasv2'

    entity = 'lbaas_member'

    res_info_key = 'member'

    PROPERTIES = (
        POOL, ADDRESS, PROTOCOL_PORT, WEIGHT, ADMIN_STATE_UP,
        SUBNET,
    ) = (
        'pool', 'address', 'protocol_port', 'weight', 'admin_state_up',
        'subnet'
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
                constraints.CustomConstraint('neutron.lbaas.pool')
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
            # Make this required untill bug #1585100 is resolved.
            required=True
        ),
    }

    attributes_schema = {
        ADDRESS_ATTR: attributes.Schema(
            _('The IP address of the pool member.'),
            type=attributes.Schema.STRING
        ),
        POOL_ID_ATTR: attributes.Schema(
            _('The ID of the pool to which the pool member belongs.'),
            type=attributes.Schema.STRING
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SUBNET],
                client_plugin=self.client_plugin(),
                finder='find_resourceid_by_name_or_id',
                entity='subnet'
            ),
        ]

    def __init__(self, name, definition, stack):
        super(PoolMember, self).__init__(name, definition, stack)
        self._pool_id = None
        self._lb_id = None

    @property
    def pool_id(self):
        if self._pool_id is None:
            client_plugin = self.client_plugin()
            self._pool_id = client_plugin.find_resourceid_by_name_or_id(
                client_plugin.RES_TYPE_LB_POOL,
                self.properties[self.POOL])
        return self._pool_id

    @property
    def lb_id(self):
        if self._lb_id is None:
            pool = self.client().show_lbaas_pool(self.pool_id)['pool']

            listener_id = pool['listeners'][0]['id']
            listener = self.client().show_listener(listener_id)['listener']

            self._lb_id = listener['loadbalancers'][0]['id']
        return self._lb_id

    def _check_lb_status(self):
        return self.client_plugin().check_lb_status(self.lb_id)

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        self.client_plugin().resolve_pool(
            properties, self.POOL, 'pool_id')
        properties.pop('pool_id')
        properties['subnet_id'] = properties.pop(self.SUBNET)
        return properties

    def check_create_complete(self, properties):
        if self.resource_id is None:
            try:
                member = self.client().create_lbaas_member(
                    self.pool_id, {'member': properties})['member']
                self.resource_id_set(member['id'])
            except Exception as ex:
                if self.client_plugin().is_invalid(ex):
                    return False
                raise

        return self._check_lb_status()

    def _res_get_args(self):
        return [self.resource_id, self.pool_id]

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self._update_called = False
        return prop_diff

    def check_update_complete(self, prop_diff):
        if not prop_diff:
            return True

        if not self._update_called:
            try:
                self.client().update_lbaas_member(self.resource_id,
                                                  self.pool_id,
                                                  {'member': prop_diff})
                self._update_called = True
            except Exception as ex:
                if self.client_plugin().is_invalid(ex):
                    return False
                raise

        return self._check_lb_status()

    def handle_delete(self):
        self._delete_called = False

    def check_delete_complete(self, data):
        if self.resource_id is None:
            return True

        if not self._delete_called:
            try:
                self.client().delete_lbaas_member(self.resource_id,
                                                  self.pool_id)
                self._delete_called = True
            except Exception as ex:
                if self.client_plugin().is_invalid(ex):
                    return False
                elif self.client_plugin().is_not_found(ex):
                    return True
                raise

        return self._check_lb_status()


def resource_mapping():
    return {
        'OS::Neutron::LBaaS::PoolMember': PoolMember,
    }
