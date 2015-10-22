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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support


class Listener(neutron.NeutronResource):
    """A resource for managing LBaaS v2 Listeners.

    This resource creates and manages Neutron LBaaS v2 Listeners,
    which represent a listening endpoint for the vip.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'lbaasv2'

    PROPERTIES = (
        PROTOCOL_PORT, PROTOCOL, LOADBALANCER, NAME,
        ADMIN_STATE_UP, DESCRIPTION, DEFAULT_TLS_CONTAINER_REF,
        SNI_CONTAINER_REFS, CONNECTION_LIMIT, TENANT_ID
    ) = (
        'protocol_port', 'protocol', 'loadbalancer', 'name',
        'admin_state_up', 'description', 'default_tls_container_ref',
        'sni_container_refs', 'connection_limit', 'tenant_id'
    )

    PROTOCOLS = (
        TCP, HTTP, HTTPS, TERMINATED_HTTPS,
    ) = (
        'TCP', 'HTTP', 'HTTPS', 'TERMINATED_HTTPS',
    )

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
                constraints.AllowedValues(PROTOCOLS),
            ]
        ),
        LOADBALANCER: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the load balancer with which listener '
              'is associated.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.lbaas.loadbalancer')
            ]
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

    def __init__(self, name, definition, stack):
        super(Listener, self).__init__(name, definition, stack)
        self._lb_id = None

    @property
    def lb_id(self):
        if self._lb_id is None:
            self._lb_id = self.client_plugin().find_resourceid_by_name_or_id(
                'loadbalancer', self.properties[self.LOADBALANCER])
        return self._lb_id

    def validate(self):
        res = super(Listener, self).validate()
        if res:
            return res

        if self.properties[self.PROTOCOL] == self.TERMINATED_HTTPS:
            if self.properties[self.DEFAULT_TLS_CONTAINER_REF] is None:
                msg = (_('Property %(ref)s required when protocol is '
                       '%(term)s.') % {'ref': self.DEFAULT_TLS_CONTAINER_REF,
                                       'term': self.TERMINATED_HTTPS})
                raise exception.StackValidationFailed(message=msg)

    def _check_lb_status(self):
        return self.client_plugin().check_lb_status(self.lb_id)

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        self.client_plugin().resolve_loadbalancer(
            properties, self.LOADBALANCER, 'loadbalancer_id')

        return properties

    def check_create_complete(self, properties):
        if not self._check_lb_status():
            return False

        if self.resource_id is None:
            listener = self.client().create_listener(
                {'listener': properties})['listener']
            self.resource_id_set(listener['id'])
            return False

        return True

    def _show_resource(self):
        return self.client().show_listener(
            self.resource_id)['listener']

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self._update_called = False
        return prop_diff

    def check_update_complete(self, prop_diff):
        if not prop_diff:
            return True

        if self._update_called:
            return self._check_lb_status()

        if self._check_lb_status():
            self.client().update_listener(self.resource_id,
                                          {'listener': prop_diff})
            self._update_called = True

        return False

    def handle_delete(self):
        self._delete_called = False

    def check_delete_complete(self, data):
        if self.resource_id is None:
            return True

        if self._delete_called:
            return self._check_lb_status()

        if self._check_lb_status():
            with self.client_plugin().ignore_not_found:
                self.client().delete_listener(self.resource_id)
            self._delete_called = True

        return False


def resource_mapping():
    return {
        'OS::Neutron::LBaaS::Listener': Listener,
    }
