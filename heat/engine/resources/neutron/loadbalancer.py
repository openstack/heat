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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.neutron import neutron
from heat.engine import scheduler
from heat.engine import support


class HealthMonitor(neutron.NeutronResource):
    """
    A resource for managing health monitors for load balancers in Neutron.
    """

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
        SHOW,
    ) = (
        'admin_state_up', 'delay', 'expected_codes', 'http_method',
        'max_retries', 'timeout', 'type', 'url_path', 'tenant_id',
        'show',
    )

    properties_schema = {
        DELAY: properties.Schema(
            properties.Schema.INTEGER,
            _('The minimum time in seconds between regular connections of '
              'the member.'),
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
            _('Maximum number of seconds for a monitor to wait for a '
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
            _('The administrative state of this health monitor.')
        ),
        DELAY_ATTR: attributes.Schema(
            _('The minimum time in seconds between regular connections '
              'of the member.')
        ),
        EXPECTED_CODES_ATTR: attributes.Schema(
            _('The list of HTTP status codes expected in response '
              'from the member to declare it healthy.')
        ),
        HTTP_METHOD_ATTR: attributes.Schema(
            _('The HTTP method used for requests by the monitor of type HTTP.')
        ),
        MAX_RETRIES_ATTR: attributes.Schema(
            _('Number of permissible connection failures before changing '
              'the member status to INACTIVE.')
        ),
        TIMEOUT_ATTR: attributes.Schema(
            _('Maximum number of seconds for a monitor to wait for a '
              'connection to be established before it times out.')
        ),
        TYPE_ATTR: attributes.Schema(
            _('One of predefined health monitor types.')
        ),
        URL_PATH_ATTR: attributes.Schema(
            _('The HTTP path used in the HTTP request used by the monitor '
              'to test a member health.')
        ),
        TENANT_ID: attributes.Schema(
            _('Tenant owning the health monitor.')
        ),
        SHOW: attributes.Schema(
            _('All attributes.')
        ),
    }

    def handle_create(self):
        properties = self.prepare_properties(
            self.properties,
            self.physical_resource_name())
        health_monitor = self.neutron().create_health_monitor(
            {'health_monitor': properties})['health_monitor']
        self.resource_id_set(health_monitor['id'])

    def _show_resource(self):
        return self.neutron().show_health_monitor(
            self.resource_id)['health_monitor']

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_health_monitor(
                self.resource_id, {'health_monitor': prop_diff})

    def handle_delete(self):
        try:
            self.neutron().delete_health_monitor(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return self._delete_task()


class Pool(neutron.NeutronResource):
    """
    A resource for managing load balancer pools in Neutron.
    """

    PROPERTIES = (
        PROTOCOL, SUBNET_ID, SUBNET, LB_METHOD, NAME, DESCRIPTION,
        ADMIN_STATE_UP, VIP, MONITORS,
    ) = (
        'protocol', 'subnet_id', 'subnet', 'lb_method', 'name', 'description',
        'admin_state_up', 'vip', 'monitors',
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
        LB_METHOD_ATTR, DESCRIPTION_ATTR, TENANT_ID, VIP_ATTR,
    ) = (
        'admin_state_up', 'name', 'protocol', 'subnet_id',
        'lb_method', 'description', 'tenant_id', 'vip',
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
                support.DEPRECATED,
                _('Use property %s.') % SUBNET),
            required=False
        ),
        SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('The subnet for the port on which the members '
              'of the pool will be connected.'),
            required=False
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
                    _('Subnet of the vip.')
                ),
                VIP_ADDRESS: properties.Schema(
                    properties.Schema.STRING,
                    _('IP address of the vip.')
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
            _('The administrative state of this pool.')
        ),
        NAME_ATTR: attributes.Schema(
            _('Name of the pool.')
        ),
        PROTOCOL_ATTR: attributes.Schema(
            _('Protocol to balance.')
        ),
        SUBNET_ID_ATTR: attributes.Schema(
            _('The subnet for the port on which the members of the pool '
              'will be connected.')
        ),
        LB_METHOD_ATTR: attributes.Schema(
            _('The algorithm used to distribute load between the members '
              'of the pool.')
        ),
        DESCRIPTION_ATTR: attributes.Schema(
            _('Description of the pool.')
        ),
        TENANT_ID: attributes.Schema(
            _('Tenant owning the pool.')
        ),
        VIP_ATTR: attributes.Schema(
            _('Vip associated with the pool.')
        ),
    }

    def validate(self):
        res = super(Pool, self).validate()
        if res:
            return res
        self._validate_depr_property_required(
            self.properties, self.SUBNET, self.SUBNET_ID)
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
        self.client_plugin().resolve_subnet(
            properties, self.SUBNET, 'subnet_id')
        vip_properties = properties.pop(self.VIP)
        monitors = properties.pop(self.MONITORS)
        client = self.neutron()
        pool = client.create_pool({'pool': properties})['pool']
        self.resource_id_set(pool['id'])

        for monitor in monitors:
            client.associate_health_monitor(
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
            vip_arguments['subnet_id'] = properties[self.SUBNET_ID]
        else:
            vip_arguments['subnet_id'] = self.client_plugin().resolve_subnet(
                vip_arguments, self.VIP_SUBNET, 'subnet_id')

        vip_arguments['pool_id'] = pool['id']
        vip = client.create_vip({'vip': vip_arguments})['vip']

        self.metadata_set({'vip': vip['id']})

    def _show_resource(self):
        return self.neutron().show_pool(self.resource_id)['pool']

    def check_create_complete(self, data):
        attributes = self._show_resource()
        status = attributes['status']
        if status == 'PENDING_CREATE':
            return False
        elif status == 'ACTIVE':
            vip_attributes = self.neutron().show_vip(
                self.metadata_get()['vip'])['vip']
            vip_status = vip_attributes['status']
            if vip_status == 'PENDING_CREATE':
                return False
            if vip_status == 'ACTIVE':
                return True
            if vip_status == 'ERROR':
                raise resource.ResourceInError(
                    resource_status=vip_status,
                    status_reason=_('error in vip'))
            raise resource.ResourceUnknownStatus(
                resource_status=vip_status,
                result=_('Pool creation failed due to vip'))
        elif status == 'ERROR':
            raise resource.ResourceInError(
                resource_status=status,
                status_reason=_('error in pool'))
        else:
            raise resource.ResourceUnknownStatus(
                resource_status=status,
                result=_('Pool creation failed'))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            client = self.neutron()
            if self.MONITORS in prop_diff:
                monitors = set(prop_diff.pop(self.MONITORS))
                old_monitors = set(self.properties[self.MONITORS])
                for monitor in old_monitors - monitors:
                    client.disassociate_health_monitor(self.resource_id,
                                                       monitor)
                for monitor in monitors - old_monitors:
                    client.associate_health_monitor(
                        self.resource_id, {'health_monitor': {'id': monitor}})

            if prop_diff:
                client.update_pool(self.resource_id, {'pool': prop_diff})

    def _resolve_attribute(self, name):
        if name == self.VIP_ATTR:
            return self.neutron().show_vip(self.metadata_get()['vip'])['vip']
        return super(Pool, self)._resolve_attribute(name)

    def _confirm_vip_delete(self):
        client = self.neutron()
        while True:
            try:
                yield
                client.show_vip(self.metadata_get()['vip'])
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)
                break

    def handle_delete(self):
        checkers = []
        if self.metadata_get():
            try:
                self.neutron().delete_vip(self.metadata_get()['vip'])
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)
            else:
                checkers.append(scheduler.TaskRunner(self._confirm_vip_delete))
        try:
            self.neutron().delete_pool(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            checkers.append(scheduler.TaskRunner(self._confirm_delete))
        return checkers

    def check_delete_complete(self, checkers):
        '''Push all checkers to completion in list order.'''
        for checker in checkers:
            if not checker.started():
                checker.start()
            if not checker.step():
                return False
        return True


class PoolMember(neutron.NeutronResource):
    """
    A resource to handle load balancer members.
    """

    PROPERTIES = (
        POOL_ID, ADDRESS, PROTOCOL_PORT, WEIGHT, ADMIN_STATE_UP,
    ) = (
        'pool_id', 'address', 'protocol_port', 'weight', 'admin_state_up',
    )

    ATTRIBUTES = (
        ADMIN_STATE_UP_ATTR, TENANT_ID, WEIGHT_ATTR, ADDRESS_ATTR,
        POOL_ID_ATTR, PROTOCOL_PORT_ATTR, SHOW,
    ) = (
        'admin_state_up', 'tenant_id', 'weight', 'address',
        'pool_id', 'protocol_port', 'show',
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
            required=True
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
            _('The administrative state of this pool member.')
        ),
        TENANT_ID: attributes.Schema(
            _('Tenant owning the pool member.')
        ),
        WEIGHT_ATTR: attributes.Schema(
            _('Weight of the pool member in the pool.')
        ),
        ADDRESS_ATTR: attributes.Schema(
            _('IP address of the pool member.')
        ),
        POOL_ID_ATTR: attributes.Schema(
            _('The ID of the load balancing pool.')
        ),
        PROTOCOL_PORT_ATTR: attributes.Schema(
            _('TCP port on which the pool member listens for requests or '
              'connections.')
        ),
        SHOW: attributes.Schema(
            _('All attributes.')
        ),
    }

    def handle_create(self):
        pool = self.properties[self.POOL_ID]
        client = self.neutron()
        protocol_port = self.properties[self.PROTOCOL_PORT]
        address = self.properties[self.ADDRESS]
        admin_state_up = self.properties[self.ADMIN_STATE_UP]
        weight = self.properties.get(self.WEIGHT)

        params = {
            'pool_id': pool,
            'address': address,
            'protocol_port': protocol_port,
            'admin_state_up': admin_state_up
        }

        if weight is not None:
            params['weight'] = weight

        member = client.create_member({'member': params})['member']
        self.resource_id_set(member['id'])

    def _show_resource(self):
        return self.neutron().show_member(self.resource_id)['member']

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.neutron().update_member(
                self.resource_id, {'member': prop_diff})

    def handle_delete(self):
        client = self.neutron()
        try:
            client.delete_member(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return self._delete_task()


class LoadBalancer(resource.Resource):
    """
    A resource to link a neutron pool with servers.
    """

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
            required=True
        ),
        MEMBERS: properties.Schema(
            properties.Schema.LIST,
            _('The list of Nova server IDs load balanced.'),
            default=[],
            update_allowed=True
        ),
    }

    default_client_name = 'neutron'

    def handle_create(self):
        pool = self.properties[self.POOL_ID]
        client = self.neutron()
        protocol_port = self.properties[self.PROTOCOL_PORT]

        for member in self.properties.get(self.MEMBERS):
            address = self.client_plugin('nova').server_to_ipaddress(member)
            lb_member = client.create_member({
                'member': {
                    'pool_id': pool,
                    'address': address,
                    'protocol_port': protocol_port}})['member']
            self.data_set(member, lb_member['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if self.MEMBERS in prop_diff:
            members = set(prop_diff[self.MEMBERS])
            rd_members = self.data()
            old_members = set(rd_members.keys())
            client = self.neutron()
            for member in old_members - members:
                member_id = rd_members[member]
                try:
                    client.delete_member(member_id)
                except Exception as ex:
                    self.client_plugin().ignore_not_found(ex)
                self.data_delete(member)
            pool = self.properties[self.POOL_ID]
            protocol_port = self.properties[self.PROTOCOL_PORT]
            for member in members - old_members:
                address = self.client_plugin('nova').server_to_ipaddress(
                    member)
                lb_member = client.create_member({
                    'member': {
                        'pool_id': pool,
                        'address': address,
                        'protocol_port': protocol_port}})['member']
                self.data_set(member, lb_member['id'])

    def handle_delete(self):
        client = self.neutron()
        for member in self.properties.get(self.MEMBERS):
            member_id = self.data().get(member)
            try:
                client.delete_member(member_id)
            except Exception as ex:
                self.client_plugin().ignore_not_found(ex)
            self.data_delete(member)


def resource_mapping():
    return {
        'OS::Neutron::HealthMonitor': HealthMonitor,
        'OS::Neutron::Pool': Pool,
        'OS::Neutron::PoolMember': PoolMember,
        'OS::Neutron::LoadBalancer': LoadBalancer,
    }
