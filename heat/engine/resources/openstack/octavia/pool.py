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


class Pool(octavia_base.OctaviaBase):
    """A resource for managing Octavia Pools.

    This resources manages octavia LBaaS Pools, which represent a group
    of nodes. Pools define the subnet where nodes reside, balancing algorithm,
    and the nodes themselves.
    """

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

    SUPPORTED_PROTOCOLS = (TCP, HTTP, HTTPS, TERMINATED_HTTPS, PROXY, UDP) = (
        'TCP', 'HTTP', 'HTTPS', 'TERMINATED_HTTPS', 'PROXY', 'UDP')

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
                constraints.CustomConstraint('octavia.listener')
            ]
        ),
        LOADBALANCER: properties.Schema(
            properties.Schema.STRING,
            _('Loadbalancer name or ID to be associated with this pool.'),
            constraints=[
                constraints.CustomConstraint('octavia.loadbalancer')
            ],
        ),
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('Protocol of the pool.'),
            required=True,
            constraints=[
                constraints.AllowedValues(SUPPORTED_PROTOCOLS),
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
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LISTENER],
                client_plugin=self.client_plugin(),
                finder='get_listener',
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.LOADBALANCER],
                client_plugin=self.client_plugin(),
                finder='get_loadbalancer',
            ),
        ]

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items() if v is not None)
        if self.NAME not in props:
            props[self.NAME] = self.physical_resource_name()
        if self.LISTENER in props:
            props['listener_id'] = props.pop(self.LISTENER)
        if self.LOADBALANCER in props:
            props['loadbalancer_id'] = props.pop(self.LOADBALANCER)
        session_p = props.get(self.SESSION_PERSISTENCE)
        if session_p is not None:
            session_props = dict(
                (k, v) for k, v in session_p.items() if v is not None)
            props[self.SESSION_PERSISTENCE] = session_props
        return props

    def validate(self):
        super(Pool, self).validate()
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

    def _resource_create(self, properties):
        return self.client().pool_create(json={'pool': properties})['pool']

    def _resource_update(self, prop_diff):
        self.client().pool_set(self.resource_id, json={'pool': prop_diff})

    def _resource_delete(self):
        self.client().pool_delete(self.resource_id)

    def _show_resource(self):
        return self.client().pool_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::Pool': Pool,
    }
