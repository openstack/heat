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


class HealthMonitor(neutron.NeutronResource):
    """A resource to handle load balancer health monitors.

    This resource creates and manages Neutron LBaaS v2 healthmonitors,
    which watches status of the load balanced servers.
    """

    support_status = support.SupportStatus(version='6.0.0')

    required_service_extension = 'lbaasv2'

    entity = 'lbaas_healthmonitor'

    res_info_key = 'healthmonitor'

    # Properties inputs for the resources create/update.
    PROPERTIES = (
        ADMIN_STATE_UP, DELAY, EXPECTED_CODES, HTTP_METHOD,
        MAX_RETRIES, POOL, TIMEOUT, TYPE, URL_PATH, TENANT_ID
    ) = (
        'admin_state_up', 'delay', 'expected_codes', 'http_method',
        'max_retries', 'pool', 'timeout', 'type', 'url_path', 'tenant_id'
    )

    # Supported HTTP methods
    HTTP_METHODS = (
        GET, HEAT, POST, PUT, DELETE, TRACE, OPTIONS,
        CONNECT, PATCH
    ) = (
        'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'TRACE', 'OPTIONS',
        'CONNECT', 'PATCH'
    )

    # Supported output attributes of the resources.
    ATTRIBUTES = (POOLS_ATTR) = ('pools')

    properties_schema = {
        ADMIN_STATE_UP: properties.Schema(
            properties.Schema.BOOLEAN,
            _('The administrative state of the health monitor.'),
            default=True,
            update_allowed=True
        ),
        DELAY: properties.Schema(
            properties.Schema.INTEGER,
            _('The minimum time in milliseconds between regular connections '
              'of the member.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.Range(min=0)]
        ),
        EXPECTED_CODES: properties.Schema(
            properties.Schema.STRING,
            _('The HTTP status codes expected in response from the '
              'member to declare it healthy. Specify one of the following '
              'values: a single value, such as 200. a list, such as 200, 202. '
              'a range, such as 200-204.'),
            update_allowed=True,
            default='200'
        ),
        HTTP_METHOD: properties.Schema(
            properties.Schema.STRING,
            _('The HTTP method used for requests by the monitor of type '
              'HTTP.'),
            update_allowed=True,
            default=GET,
            constraints=[constraints.AllowedValues(HTTP_METHODS)]
        ),
        MAX_RETRIES: properties.Schema(
            properties.Schema.INTEGER,
            _('Number of permissible connection failures before changing the '
              'member status to INACTIVE.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.Range(min=1, max=10)],
        ),
        POOL: properties.Schema(
            properties.Schema.STRING,
            _('ID or name of the load balancing pool.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('neutron.lbaas.pool')
            ]
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _('Maximum number of milliseconds for a monitor to wait for a '
              'connection to be established before it times out.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.Range(min=0)]
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('One of predefined health monitor types.'),
            required=True,
            constraints=[
                constraints.AllowedValues(['PING', 'TCP', 'HTTP', 'HTTPS']),
            ]
        ),
        URL_PATH: properties.Schema(
            properties.Schema.STRING,
            _('The HTTP path used in the HTTP request used by the monitor to '
              'test a member health. A valid value is a string the begins '
              'with a forward slash (/).'),
            update_allowed=True,
            default='/'
        ),
        TENANT_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the tenant who owns the health monitor.')
        )
    }

    attributes_schema = {
        POOLS_ATTR: attributes.Schema(
            _('The list of Pools related to this monitor.'),
            type=attributes.Schema.LIST
        )
    }

    def __init__(self, name, definition, stack):
        super(HealthMonitor, self).__init__(name, definition, stack)
        self._lb_id = None

    @property
    def lb_id(self):
        if self._lb_id is None:
            client_plugin = self.client_plugin()
            pool_id = client_plugin.find_resourceid_by_name_or_id(
                client_plugin.RES_TYPE_LB_POOL,
                self.properties[self.POOL])
            pool = self.client().show_lbaas_pool(pool_id)['pool']

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

        return properties

    def check_create_complete(self, properties):
        if self.resource_id is None:
            try:
                healthmonitor = self.client().create_lbaas_healthmonitor(
                    {'healthmonitor': properties})['healthmonitor']
                self.resource_id_set(healthmonitor['id'])
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
                self.client().update_lbaas_healthmonitor(
                    self.resource_id, {'healthmonitor': prop_diff})
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
                self.client().delete_lbaas_healthmonitor(self.resource_id)
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
        'OS::Neutron::LBaaS::HealthMonitor': HealthMonitor,
    }
