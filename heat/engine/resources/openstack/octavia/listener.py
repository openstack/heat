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
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.octavia import octavia_base
from heat.engine import translation


class Listener(octavia_base.OctaviaBase):
    """A resource for managing octavia Listeners.

    This resource creates and manages Neutron octavia Listeners,
    which represent a listening endpoint for the vip.
    """

    PROPERTIES = (
        PROTOCOL_PORT, PROTOCOL, LOADBALANCER, DEFAULT_POOL, NAME,
        ADMIN_STATE_UP, DESCRIPTION, DEFAULT_TLS_CONTAINER_REF,
        SNI_CONTAINER_REFS, CONNECTION_LIMIT, TENANT_ID
    ) = (
        'protocol_port', 'protocol', 'loadbalancer', 'default_pool', 'name',
        'admin_state_up', 'description', 'default_tls_container_ref',
        'sni_container_refs', 'connection_limit', 'tenant_id'
    )

    SUPPORTED_PROTOCOLS = (TCP, HTTP, HTTPS, TERMINATED_HTTPS, PROXY, UDP) = (
        'TCP', 'HTTP', 'HTTPS', 'TERMINATED_HTTPS', 'PROXY', 'UDP')

    ATTRIBUTES = (
        LOADBALANCERS_ATTR, DEFAULT_POOL_ID_ATTR
    ) = (
        'loadbalancers', 'default_pool_id'
    )

    properties_schema = {
        PROTOCOL_PORT: properties.Schema(
            properties.Schema.INTEGER,
            _('TCP or UDP port on which to listen for client traffic.'),
            required=True,
            constraints=[
                constraints.Range(1, 65535),
            ]
        ),
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('Protocol on which to listen for the client traffic.'),
            required=True,
            constraints=[
                constraints.AllowedValues(SUPPORTED_PROTOCOLS),
            ]
        ),
        LOADBALANCER: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the load balancer with which listener '
              'is associated.'),
            constraints=[
                constraints.CustomConstraint('octavia.loadbalancer')
            ]
        ),
        DEFAULT_POOL: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the default pool for the listener.'),
            update_allowed=True,
            constraints=[
                constraints.CustomConstraint('octavia.pool')
            ],
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of this listener.'),
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of this listener.'),
            update_allowed=True,
            default=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of this listener.'),
            update_allowed=True,
            default=''
        ),
        DEFAULT_TLS_CONTAINER_REF: properties.Schema(
            properties.Schema.STRING,
            _('Default TLS container reference to retrieve TLS '
              'information.'),
            update_allowed=True
        ),
        SNI_CONTAINER_REFS: properties.Schema(
            properties.Schema.LIST,
            _('List of TLS container references for SNI.'),
            update_allowed=True
        ),
        CONNECTION_LIMIT: properties.Schema(
            properties.Schema.INTEGER,
            _('The maximum number of connections permitted for this '
              'load balancer. Defaults to -1, which is infinite.'),
            update_allowed=True,
            default=-1,
            constraints=[
                constraints.Range(min=-1),
            ]
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the tenant who owns the listener.')
        ),
    }

    attributes_schema = {
        LOADBALANCERS_ATTR: attributes.Schema(
            _('ID of the load balancer this listener is associated to.'),
            type=attributes.Schema.LIST
        ),
        DEFAULT_POOL_ID_ATTR: attributes.Schema(
            _('ID of the default pool this listener is associated to.'),
            type=attributes.Schema.STRING
        )
    }

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LOADBALANCER],
                client_plugin=self.client_plugin(),
                finder='get_loadbalancer',
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.DEFAULT_POOL],
                client_plugin=self.client_plugin(),
                finder='get_pool'
            ),
        ]

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items() if v is not None)
        if self.NAME not in props:
            props[self.NAME] = self.physical_resource_name()
        if self.LOADBALANCER in props:
            props['loadbalancer_id'] = props.pop(self.LOADBALANCER)
        if self.DEFAULT_POOL in props:
            props['default_pool_id'] = props.pop(self.DEFAULT_POOL)
        return props

    def validate(self):
        super(Listener, self).validate()
        if (self.properties[self.LOADBALANCER] is None
                and self.properties[self.DEFAULT_POOL] is None):
            raise exception.PropertyUnspecifiedError(self.LOADBALANCER,
                                                     self.DEFAULT_POOL)

        if self.properties[self.PROTOCOL] == self.TERMINATED_HTTPS:
            if self.properties[self.DEFAULT_TLS_CONTAINER_REF] is None:
                msg = (_('Property %(ref)s required when protocol is '
                       '%(term)s.') % {'ref': self.DEFAULT_TLS_CONTAINER_REF,
                                       'term': self.TERMINATED_HTTPS})
                raise exception.StackValidationFailed(message=msg)

    def _resource_create(self, properties):
        return self.client().listener_create(
            json={'listener': properties})['listener']

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self._update_called = False
        if self.DEFAULT_POOL in prop_diff:
            prop_diff['default_pool_id'] = prop_diff.pop(self.DEFAULT_POOL)
        return prop_diff

    def _resource_update(self, prop_diff):
        self.client().listener_set(self.resource_id,
                                   json={'listener': prop_diff})

    def _resource_delete(self):
        self.client().listener_delete(self.resource_id)

    def _show_resource(self):
        return self.client().listener_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::Listener': Listener,
    }
