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
from heat.engine.clients import progress
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.neutron import neutron
from heat.engine import support
from heat.engine import translation

DEPR_MSG = _('Neutron LBaaS v1 is deprecated in the Liberty release '
             'and is planned to be removed in a future release. '
             'Going forward, the LBaaS V2 should be used.')


class HealthMonitor(neutron.NeutronResource):
    """A resource for managing health monitors for loadbalancers in Neutron.

    A health monitor is used to determine whether or not back-end members of
    the VIP's pool are usable for processing a request. A pool can have several
    health monitors associated with it. There are different types of health
    monitors supported by the OpenStack LBaaS service:

      - PING: used to ping the members using ICMP.
      - TCP: used to connect to the members using TCP.
      - HTTP: used to send an HTTP request to the member.
      - HTTPS: used to send a secure HTTP request to the member.
    """

    required_service_extension = 'lbaas'

    entity = 'health_monitor'

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0'
        )
    )

    PROPERTIES = (
        DELAY, TYPE, MAX_RETRIES, TIMEOUT, ADMIN_STATE_UP,
        HTTP_METHOD, EXPECTED_CODES, URL_PATH,
    ) = (
        'delay', 'type', 'max_retries', 'timeout', 'admin_state_up',
        'http_method', 'expected_codes', 'url_path',
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, DELAY_ATTR, EXPECTED_CODES_ATTR, HTTP_METHOD_ATTR,
        MAX_RETRIES_ATTR, TIMEOUT_ATTR, TYPE_ATTR, URL_PATH_ATTR, TENANT_ID,
    ) = (
        'admin_state_up', 'delay', 'expected_codes', 'http_method',
        'max_retries', 'timeout', 'type', 'url_path', 'tenant_id',
    )

    properties_schema = {
        DELAY: properties.Schema(
            properties.Schema.INTEGER,
            _('The minimum time in milliseconds between regular connections '
              'of the member.'),
            required=True,
            update_allowed=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('One of predefined health monitor types.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['PING', 'TCP', 'HTTP', 'HTTPS']),
            ]
        ),
        MAX_RETRIES: properties.Schema(
            properties.Schema.INTEGER,
            _('Number of permissible connection failures before changing the '
              'member status to INACTIVE.'),
            required=True,
            update_allowed=True
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('Maximum number of milliseconds for a monitor to wait for a '
              'connection to be established before it times out.'),
            required=True,
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of the health monitor.'),
            default=True,
            update_allowed=True
        ),
        HTTP_METHOD: properties.Schema(
            properties.Schema.STRING,
            _('The HTTP method used for requests by the monitor of type '
              'HTTP.'),
            update_allowed=True
        ),
        EXPECTED_CODES: properties.Schema(
            properties.Schema.STRING,
            _('The list of HTTP status codes expected in response from the '
              'member to declare it healthy.'),
            update_allowed=True
        ),
        URL_PATH: properties.Schema(
            properties.Schema.STRING,
            _('The HTTP path used in the HTTP request used by the monitor to '
              'test a member health.'),
            update_allowed=True
        ),
    }

    attributes_schema = {
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _('The administrative state of this health monitor.'),
            type=attributes.Schema.STRING
        ),
        DELAY_ATTR: attributes.Schema(
            _('The minimum time in milliseconds between regular connections '
              'of the member.'),
            type=attributes.Schema.STRING
        ),
        EXPECTED_CODES_ATTR: attributes.Schema(
            _('The list of HTTP status codes expected in response '
              'from the member to declare it healthy.'),
            type=attributes.Schema.LIST
        ),
        HTTP_METHOD_ATTR: attributes.Schema(
            _('The HTTP method used for requests by the monitor of '
              'type HTTP.'),
            type=attributes.Schema.STRING
        ),
        MAX_RETRIES_ATTR: attributes.Schema(
            _('Number of permissible connection failures before changing '
              'the member status to INACTIVE.'),
            type=attributes.Schema.STRING
        ),
        TIMEOUT_ATTR: attributes.Schema(
            _('Maximum number of milliseconds for a monitor to wait for a '
              'connection to be established before it times out.'),
            type=attributes.Schema.STRING
        ),
        TYPE_ATTR: attributes.Schema(
            _('One of predefined health monitor types.'),
            type=attributes.Schema.STRING
        ),
        URL_PATH_ATTR: attributes.Schema(
            _('The HTTP path used in the HTTP request used by the monitor '
              'to test a member health.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('Tenant owning the health monitor.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        health_monitor = self.client().create_health_monitor(
            {'health_monitor': properties})['health_monitor']
        self.resource_id_set(health_monitor['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_health_monitor(
                self.resource_id, {'health_monitor': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_health_monitor(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


class Pool(neutron.NeutronResource):
    """A resource for managing load balancer pools in Neutron.

    A load balancing pool is a logical set of devices, such as web servers,
    that you group together to receive and process traffic. The loadbalancing
    function chooses a member of the pool according to the configured load
    balancing method to handle the new requests or connections received on the
    VIP address. There is only one pool for a VIP.
    """

    required_service_extension = 'lbaas'

    entity = 'pool'

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0'
        )
    )

    PROPERTIES = (
        PROTOCOL, SUBNET_ID, SUBNET, LB_METHOD, NAME, DESCRIPTION,
        ADMIN_STATE_UP, VIP, MONITORS, PROVIDER,
    ) = (
        'protocol', 'subnet_id', 'subnet', 'lb_method', 'name', 'description',
        'admin_state_up', 'vip', 'monitors', 'provider',
    )

    _VIP_KEYS = (
        VIP_NAME, VIP_DESCRIPTION, VIP_SUBNET, VIP_ADDRESS,
        VIP_CONNECTION_LIMIT, VIP_PROTOCOL_PORT,
        VIP_SESSION_PERSISTENCE, VIP_ADMIN_STATE_UP,
    ) = (
        'name', 'description', 'subnet', 'address',
        'connection_limit', 'protocol_port',
        'session_persistence', 'admin_state_up',
    )

    _VIP_SESSION_PERSISTENCE_KEYS = (
        VIP_SESSION_PERSISTENCE_TYPE, VIP_SESSION_PERSISTENCE_COOKIE_NAME,
    ) = (
        'type', 'cookie_name',
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, NAME_ATTR, PROTOCOL_ATTR, SUBNET_ID_ATTR,
        LB_METHOD_ATTR, DESCRIPTION_ATTR, TENANT_ID, VIP_ATTR, PROVIDER_ATTR,
    ) = (
        'admin_state_up', 'name', 'protocol', 'subnet_id',
        'lb_method', 'description', 'tenant_id', 'vip', 'provider',
    )

    properties_schema = {
        PROTOCOL: properties.Schema(
            properties.Schema.STRING,
            _('Protocol for balancing.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['TCP', 'HTTP', 'HTTPS']),
            ]
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            support_status=support.SupportStatus(
                status=support.HIDDEN,
                version='5.0.0',
                message=_('Use property %s.') % SUBNET,
                previous_status=support.SupportStatus(
                    status=support.DEPRECATED,
                    version='2014.2'
                )
            ),
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
        SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('The subnet for the port on which the members '
              'of the pool will be connected.'),
            support_status=support.SupportStatus(version='2014.2'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.subnet')
            ]
        ),
        LB_METHOD: properties.Schema(
            properties.Schema.STRING,
            _('The algorithm used to distribute load between the members of '
              'the pool.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['ROUND_ROBIN',
                                           'LEAST_CONNECTIONS', 'SOURCE_IP']),
            ],
            update_allowed=True
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the pool.')
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the pool.'),
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of this pool.'),
            default=True,
            update_allowed=True
        ),
        PROVIDER: properties.Schema(
            properties.Schema.STRING,
            _('LBaaS provider to implement this load balancer instance.'),
            support_status=support.SupportStatus(version='5.0.0'),
            constraints=[
                constraints.CustomConstraint('neutron.lb.provider')
            ],
        ),
        VIP: properties.Schema(
            properties.Schema.MAP,
            _('IP address and port of the pool.'),
            schema={
                VIP_NAME: properties.Schema(
                    properties.Schema.STRING,
                    _('Name of the vip.')
                ),
                VIP_DESCRIPTION: properties.Schema(
                    properties.Schema.STRING,
                    _('Description of the vip.')
                ),
                VIP_SUBNET: properties.Schema(
                    properties.Schema.STRING,
                    _('Subnet of the vip.'),
                    constraints=[
                        constraints.CustomConstraint('neutron.subnet')
                    ]
                ),
                VIP_ADDRESS: properties.Schema(
                    properties.Schema.STRING,
                    _('IP address of the vip.'),
                    constraints=[
                        constraints.CustomConstraint('ip_addr')
                    ]
                ),
                VIP_CONNECTION_LIMIT: properties.Schema(
                    properties.Schema.INTEGER,
                    _('The maximum number of connections per second '
                      'allowed for the vip.')
                ),
                VIP_PROTOCOL_PORT: properties.Schema(
                    properties.Schema.INTEGER,
                    _('TCP port on which to listen for client traffic '
                      'that is associated with the vip address.'),
                    required=True
                ),
                VIP_SESSION_PERSISTENCE: properties.Schema(
                    properties.Schema.MAP,
                    _('Configuration of session persistence.'),
                    schema={
                        VIP_SESSION_PERSISTENCE_TYPE: properties.Schema(
                            properties.Schema.STRING,
                            _('Method of implementation of session '
                              'persistence feature.'),
                            required=True,
                            constraints=[constraints.AllowedValues(
                                ['SOURCE_IP', 'HTTP_COOKIE', 'APP_COOKIE']
                            )]
                        ),
                        VIP_SESSION_PERSISTENCE_COOKIE_NAME: properties.Schema(
                            properties.Schema.STRING,
                            _('Name of the cookie, '
                              'required if type is APP_COOKIE.')
                        )
                    }
                ),
                VIP_ADMIN_STATE_UP: properties.Schema(
                    properties.Schema.BOOLEAN,
                    _('The administrative state of this vip.'),
                    default=True
                ),
            },
            required=True
        ),
        MONITORS: properties.Schema(
            properties.Schema.LIST,
            _('List of health monitors associated with the pool.'),
            default=[],
            update_allowed=True
        ),
    }

    attributes_schema = {
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _('The administrative state of this pool.'),
            type=attributes.Schema.STRING
        ),
        NAME_ATTR: attributes.Schema(
            _('Name of the pool.'),
            type=attributes.Schema.STRING
        ),
        PROTOCOL_ATTR: attributes.Schema(
            _('Protocol to balance.'),
            type=attributes.Schema.STRING
        ),
        SUBNET_ID_ATTR: attributes.Schema(
            _('The subnet for the port on which the members of the pool '
              'will be connected.'),
            type=attributes.Schema.STRING
        ),
        LB_METHOD_ATTR: attributes.Schema(
            _('The algorithm used to distribute load between the members '
              'of the pool.'),
            type=attributes.Schema.STRING
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the pool.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('Tenant owning the pool.'),
            type=attributes.Schema.STRING
        ),
        VIP_ATTR: attributes.Schema(
            _('Vip associated with the pool.'),
            type=attributes.Schema.MAP
        ),
        PROVIDER_ATTR: attributes.Schema(
            _('Provider implementing this load balancer instance.'),
            support_status=support.SupportStatus(version='5.0.0'),
            type=attributes.Schema.STRING,
        ),
    }

    def translation_rules(self, props):
        client_plugin = self.client_plugin()
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.REPLACE,
                [self.SUBNET],
                value_path=[self.SUBNET_ID]
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.SUBNET],
                client_plugin=client_plugin,
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET
            ),
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.VIP, self.VIP_SUBNET],
                client_plugin=self.client_plugin(),
                finder='find_resourceid_by_name_or_id',
                entity=client_plugin.RES_TYPE_SUBNET
            )
        ]

    def validate(self):
        res = super(Pool, self).validate()
        if res:
            return res
        session_p = self.properties[self.VIP].get(self.VIP_SESSION_PERSISTENCE)
        if session_p is None:
            # session persistence is not configured, skip validation
            return

        persistence_type = session_p[self.VIP_SESSION_PERSISTENCE_TYPE]
        if persistence_type == 'APP_COOKIE':
            if session_p.get(self.VIP_SESSION_PERSISTENCE_COOKIE_NAME):
                return

            msg = _('Property cookie_name is required, when '
                    'session_persistence type is set to APP_COOKIE.')
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        subnet_id = properties.pop(self.SUBNET)
        properties['subnet_id'] = subnet_id
        vip_properties = properties.pop(self.VIP)
        monitors = properties.pop(self.MONITORS)

        pool = self.client().create_pool({'pool': properties})['pool']
        self.resource_id_set(pool['id'])

        for monitor in monitors:
            self.client().associate_health_monitor(
                pool['id'], {'health_monitor': {'id': monitor}})

        vip_arguments = self.prepare_properties(
            vip_properties,
            '%s.vip' % (self.name,))

        session_p = vip_arguments.get(self.VIP_SESSION_PERSISTENCE)
        if session_p is not None:
            prepared_props = self.prepare_properties(session_p, None)
            vip_arguments['session_persistence'] = prepared_props

        vip_arguments['protocol'] = self.properties[self.PROTOCOL]

        if vip_arguments.get(self.VIP_SUBNET) is None:
            vip_arguments['subnet_id'] = subnet_id
        else:
            vip_arguments['subnet_id'] = vip_arguments.pop(self.VIP_SUBNET)

        vip_arguments['pool_id'] = pool['id']
        vip = self.client().create_vip({'vip': vip_arguments})['vip']

        self.metadata_set({'vip': vip['id']})

    def check_create_complete(self, data):
        attributes = self._show_resource()
        status = attributes['status']
        if status == 'PENDING_CREATE':
            return False
        elif status == 'ACTIVE':
            vip_attributes = self.client().show_vip(
                self.metadata_get()['vip'])['vip']
            vip_status = vip_attributes['status']
            if vip_status == 'PENDING_CREATE':
                return False
            if vip_status == 'ACTIVE':
                return True
            if vip_status == 'ERROR':
                raise exception.ResourceInError(
                    resource_status=vip_status,
                    status_reason=_('error in vip'))
            raise exception.ResourceUnknownStatus(
                resource_status=vip_status,
                result=_('Pool creation failed due to vip'))
        elif status == 'ERROR':
            raise exception.ResourceInError(
                resource_status=status,
                status_reason=_('error in pool'))
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=status,
                result=_('Pool creation failed'))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            if self.MONITORS in prop_diff:
                monitors = set(prop_diff.pop(self.MONITORS))
                old_monitors = set(self.properties[self.MONITORS])
                for monitor in old_monitors - monitors:
                    self.client().disassociate_health_monitor(
                        self.resource_id, monitor)
                for monitor in monitors - old_monitors:
                    self.client().associate_health_monitor(
                        self.resource_id, {'health_monitor': {'id': monitor}})

            if prop_diff:
                self.client().update_pool(self.resource_id,
                                          {'pool': prop_diff})

    def _resolve_attribute(self, name):
        if name == self.VIP_ATTR:
            return self.client().show_vip(self.metadata_get()['vip'])['vip']
        return super(Pool, self)._resolve_attribute(name)

    def handle_delete(self):
        if not self.resource_id:
            prg = progress.PoolDeleteProgress(True)
            return prg

        prg = progress.PoolDeleteProgress()
        if not self.metadata_get():
            prg.vip['delete_called'] = True
            prg.vip['deleted'] = True
        return prg

    def _delete_vip(self):
        return self._not_found_in_call(
            self.client().delete_vip, self.metadata_get()['vip'])

    def _check_vip_deleted(self):
        return self._not_found_in_call(
            self.client().show_vip, self.metadata_get()['vip'])

    def _delete_pool(self):
        return self._not_found_in_call(
            self.client().delete_pool, self.resource_id)

    def check_delete_complete(self, prg):
        if not prg.vip['delete_called']:
            prg.vip['deleted'] = self._delete_vip()
            prg.vip['delete_called'] = True
            return False
        if not prg.vip['deleted']:
            prg.vip['deleted'] = self._check_vip_deleted()
            return False
        if not prg.pool['delete_called']:
            prg.pool['deleted'] = self._delete_pool()
            prg.pool['delete_called'] = True
            return prg.pool['deleted']
        if not prg.pool['deleted']:
            prg.pool['deleted'] = super(Pool, self).check_delete_complete(True)
            return prg.pool['deleted']
        return True


class PoolMember(neutron.NeutronResource):
    """A resource to handle loadbalancer members.

    A pool member represents the application running on backend server.
    """

    required_service_extension = 'lbaas'

    entity = 'member'

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0',
            previous_status=support.SupportStatus(version='2014.1')
        )
    )

    PROPERTIES = (
        POOL_ID, ADDRESS, PROTOCOL_PORT, WEIGHT, ADMIN_STATE_UP,
    ) = (
        'pool_id', 'address', 'protocol_port', 'weight', 'admin_state_up',
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, TENANT_ID, WEIGHT_ATTR, ADDRESS_ATTR,
        POOL_ID_ATTR, PROTOCOL_PORT_ATTR,
    ) = (
        'admin_state_up', 'tenant_id', 'weight', 'address',
        'pool_id', 'protocol_port',
    )

    properties_schema = {
        POOL_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the load balancing pool.'),
            required=True,
            update_allowed=True
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
            _('TCP port on which the pool member listens for requests or '
              'connections.'),
            required=True,
            constraints=[
                constraints.Range(0, 65535),
            ]
        ),
        WEIGHT: properties.Schema(
            properties.Schema.INTEGER,
            _('Weight of pool member in the pool (default to 1).'),
            constraints=[
                constraints.Range(0, 256),
            ],
            update_allowed=True
        ),
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of the pool member.'),
            default=True
        ),
    }

    attributes_schema = {
        ADMIN_STATE_UP_ATTR: attributes.Schema(
            _('The administrative state of this pool member.'),
            type=attributes.Schema.STRING
        ),
        TENANT_ID: attributes.Schema(
            _('Tenant owning the pool member.'),
            type=attributes.Schema.STRING
        ),
        WEIGHT_ATTR: attributes.Schema(
            _('Weight of the pool member in the pool.'),
            type=attributes.Schema.STRING
        ),
        ADDRESS_ATTR: attributes.Schema(
            _('IP address of the pool member.'),
            type=attributes.Schema.STRING
        ),
        POOL_ID_ATTR: attributes.Schema(
            _('The ID of the load balancing pool.'),
            type=attributes.Schema.STRING
        ),
        PROTOCOL_PORT_ATTR: attributes.Schema(
            _('TCP port on which the pool member listens for requests or '
              'connections.'),
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        pool = self.properties[self.POOL_ID]
        protocol_port = self.properties[self.PROTOCOL_PORT]
        address = self.properties[self.ADDRESS]
        admin_state_up = self.properties[self.ADMIN_STATE_UP]
        weight = self.properties[self.WEIGHT]

        params = {
            'pool_id': pool,
            'address': address,
            'protocol_port': protocol_port,
            'admin_state_up': admin_state_up
        }

        if weight is not None:
            params['weight'] = weight

        member = self.client().create_member({'member': params})['member']
        self.resource_id_set(member['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.client().update_member(
                self.resource_id, {'member': prop_diff})

    def handle_delete(self):
        try:
            self.client().delete_member(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return True


class LoadBalancer(resource.Resource):
    """A resource to link a neutron pool with servers.

    A loadbalancer allows linking a neutron pool with specified servers to some
    port.
    """

    required_service_extension = 'lbaas'

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0',
            previous_status=support.SupportStatus(version='2014.1')
        )
    )

    PROPERTIES = (
        POOL_ID, PROTOCOL_PORT, MEMBERS,
    ) = (
        'pool_id', 'protocol_port', 'members',
    )

    properties_schema = {
        POOL_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of the load balancing pool.'),
            required=True,
            update_allowed=True
        ),
        PROTOCOL_PORT: properties.Schema(
            properties.Schema.INTEGER,
            _('Port number on which the servers are running on the members.'),
            required=True,
            constraints=[
                constraints.Range(0, 65535),
            ]
        ),
        MEMBERS: properties.Schema(
            properties.Schema.LIST,
            _('The list of Nova server IDs load balanced.'),
            update_allowed=True
        ),
    }

    default_client_name = 'neutron'

    def handle_create(self):
        pool = self.properties[self.POOL_ID]
        protocol_port = self.properties[self.PROTOCOL_PORT]

        for member in self.properties[self.MEMBERS] or []:
            address = self.client_plugin('nova').server_to_ipaddress(member)
            lb_member = self.client().create_member({
                'member': {
                    'pool_id': pool,
                    'address': address,
                    'protocol_port': protocol_port}})['member']
            self.data_set(member, lb_member['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        new_props = json_snippet.properties(self.properties_schema,
                                            self.context)

        # Valid use cases are:
        # - Membership controlled by members property in template
        # - Empty members property in template; membership controlled by
        #   "updates" triggered from autoscaling group.
        # Mixing the two will lead to undefined behaviour.
        if (self.MEMBERS in prop_diff and
                (self.properties[self.MEMBERS] is not None or
                 new_props[self.MEMBERS] is not None)):
            members = set(new_props[self.MEMBERS] or [])
            rd_members = self.data()
            old_members = set(rd_members)
            for member in old_members - members:
                member_id = rd_members[member]
                with self.client_plugin().ignore_not_found:
                    self.client().delete_member(member_id)
                self.data_delete(member)
            pool = self.properties[self.POOL_ID]
            protocol_port = self.properties[self.PROTOCOL_PORT]
            for member in members - old_members:
                address = self.client_plugin('nova').server_to_ipaddress(
                    member)
                lb_member = self.client().create_member({
                    'member': {
                        'pool_id': pool,
                        'address': address,
                        'protocol_port': protocol_port}})['member']
                self.data_set(member, lb_member['id'])

    def handle_delete(self):
        # FIXME(pshchelo): this deletes members in a tight loop,
        # so is prone to OverLimit bug similar to LP 1265937
        for member, member_id in self.data().items():
            with self.client_plugin().ignore_not_found:
                self.client().delete_member(member_id)
            self.data_delete(member)


def resource_mapping():
    return {
        'OS::Neutron::HealthMonitor': HealthMonitor,
        'OS::Neutron::Pool': Pool,
        'OS::Neutron::PoolMember': PoolMember,
        'OS::Neutron::LoadBalancer': LoadBalancer,
    }
