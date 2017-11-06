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
from heat.engine import translation


class Pool(neutron.NeutronResource):
    """A resource for managing LBaaS v2 Pools.

    This resources manages Neutron-LBaaS v2 Pools, which represent a group
    of nodes. Pools define the subnet where nodes reside, balancing algorithm,
    and the nodes themselves.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'lbaasv2'

    entity = 'lbaas_pool'

    res_info_key = 'pool'

    PROPERTIES = (
        ADMIN_STATE_UP, DESCRIPTION, SESSION_PERSISTENCE, NAME,
        LB_ALGORITHM, LISTENER, LOADBALANCER, PROTOCOL,
        SESSION_PERSISTENCE_TYPE, SESSION_PERSISTENCE_COOKIE_NAME,
    ) = (
        'admin_state_up', 'description', 'session_persistence', 'name',
        'lb_algorithm', 'listener', 'loadbalancer', 'protocol',
        'type', 'cookie_name'
    )

    SESSION_PERSISTENCE_TYPES = (
        SOURCE_IP, HTTP_COOKIE, APP_COOKIE
    ) = (
        'SOURCE_IP', 'HTTP_COOKIE', 'APP_COOKIE'
    )

    ATTRIBUTES = (
        HEALTHMONITOR_ID_ATTR, LISTENERS_ATTR, MEMBERS_ATTR
    ) = (
        'healthmonitor_id', 'listeners', 'members'
    )

    properties_schema = {
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of this pool.'),
            default=True,
            update_allowed=True
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of this pool.'),
            update_allowed=True,
            default=''
        ),
        SESSION_PERSISTENCE: properties.Schema(
            properties.Schema.MAP,
            _('Configuration of session persistence.'),
            schema={
                SESSION_PERSISTENCE_TYPE: properties.Schema(
                    properties.Schema.STRING,
                    _('Method of implementation of session '
                      'persistence feature.'),
                    required=True,
                    constraints=[constraints.AllowedValues(
                        SESSION_PERSISTENCE_TYPES
                    )]
                ),
                SESSION_PERSISTENCE_COOKIE_NAME: properties.Schema(
                    properties.Schema.STRING,
                    _('Name of the cookie, '
                      'required if type is APP_COOKIE.')
                )
            },
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of this pool.'),
            update_allowed=True
        ),
        LB_ALGORITHM: properties.Schema(
            properties.Schema.STRING,
            _('The algorithm used to distribute load between the members of '
              'the pool.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['ROUND_ROBIN',
                                           'LEAST_CONNECTIONS', 'SOURCE_IP']),
            ],
            update_allowed=True,
        ),
        LISTENER: properties.Schema(
            properties.Schema.STRING,
            _('Listener name or ID to be associated with this pool.'),
            constraints=[
                constraints.CustomConstraint('neutron.lbaas.listener')
            ]
        ),
        LOADBALANCER: properties.Schema(
            properties.Schema.STRING,
            _('Loadbalancer name or ID to be associated with this pool. '
              'Requires shared_pools service extension.'),
            constraints=[
                constraints.CustomConstraint('neutron.lbaas.loadbalancer')
            ],
            support_status=support.SupportStatus(version='9.0.0')
        ),
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('Protocol of the pool.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['TCP', 'HTTP', 'HTTPS']),
            ]
        ),
    }

    attributes_schema = {
        HEALTHMONITOR_ID_ATTR: attributes.Schema(
            _('ID of the health monitor associated with this pool.'),
            type=attributes.Schema.STRING
        ),
        LISTENERS_ATTR: attributes.Schema(
            _('Listener associated with this pool.'),
            type=attributes.Schema.STRING
        ),
        MEMBERS_ATTR: attributes.Schema(
            _('Members associated with this pool.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.LIST
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LISTENER],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_LB_LISTENER
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LOADBALANCER],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_LOADBALANCER
            ),
        ]

    def __init__(self, name, definition, stack):
        super(Pool, self).__init__(name, definition, stack)
        self._lb_id = None

    @property
    def lb_id(self):
        if self._lb_id:
            return self._lb_id

        self._lb_id = self.properties[self.LOADBALANCER]
        if self._lb_id is None:
            listener_id = self.properties[self.LISTENER]
            listener = self.client().show_listener(listener_id)['listener']
            self._lb_id = listener['loadbalancers'][0]['id']
        return self._lb_id

    def validate(self):
        res = super(Pool, self).validate()
        if res:
            return res

        if (self.properties[self.LISTENER] is None and
                self.properties[self.LOADBALANCER] is None):
                raise exception.PropertyUnspecifiedError(self.LISTENER,
                                                         self.LOADBALANCER)

        if self.properties[self.SESSION_PERSISTENCE] is not None:
            session_p = self.properties[self.SESSION_PERSISTENCE]
            persistence_type = session_p[self.SESSION_PERSISTENCE_TYPE]
            if persistence_type == self.APP_COOKIE:
                if not session_p.get(self.SESSION_PERSISTENCE_COOKIE_NAME):
                    msg = (_('Property %(cookie)s is required when %(sp)s '
                             'type is set to %(app)s.') %
                           {'cookie': self.SESSION_PERSISTENCE_COOKIE_NAME,
                            'sp': self.SESSION_PERSISTENCE,
                            'app': self.APP_COOKIE})
                    raise exception.StackValidationFailed(message=msg)
            elif persistence_type == self.SOURCE_IP:
                if session_p.get(self.SESSION_PERSISTENCE_COOKIE_NAME):
                    msg = (_('Property %(cookie)s must NOT be specified when '
                             '%(sp)s type is set to %(ip)s.') %
                           {'cookie': self.SESSION_PERSISTENCE_COOKIE_NAME,
                            'sp': self.SESSION_PERSISTENCE,
                            'ip': self.SOURCE_IP})
                    raise exception.StackValidationFailed(message=msg)

    def _check_lb_status(self):
        return self.client_plugin().check_lb_status(self.lb_id)

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())

        if self.LISTENER in properties:
            properties['listener_id'] = properties.pop(self.LISTENER)
        if self.LOADBALANCER in properties:
            properties['loadbalancer_id'] = properties.pop(self.LOADBALANCER)

        session_p = properties.get(self.SESSION_PERSISTENCE)
        if session_p is not None:
            session_props = self.prepare_properties(session_p, None)
            properties[self.SESSION_PERSISTENCE] = session_props

        return properties

    def check_create_complete(self, properties):
        if self.resource_id is None:
            try:
                pool = self.client().create_lbaas_pool(
                    {'pool': properties})['pool']
                self.resource_id_set(pool['id'])
            except Exception as ex:
                if self.client_plugin().is_invalid(ex):
                    return False
                raise

        return self._check_lb_status()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self._update_called = False
        return prop_diff

    def check_update_complete(self, prop_diff):
        if not prop_diff:
            return True

        if not self._update_called:
            try:
                self.client().update_lbaas_pool(
                    self.resource_id, {'pool': prop_diff})
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
                self.client().delete_lbaas_pool(self.resource_id)
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
        'OS::Neutron::LBaaS::Pool': Pool,
    }
