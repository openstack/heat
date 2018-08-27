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


class HealthMonitor(octavia_base.OctaviaBase):
    """A resource to handle load balancer health monitors.

    This resource creates and manages octavia healthmonitors,
    which watches status of the load balanced servers.
    """

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
        ),
        HTTP_METHOD: properties.Schema(
            properties.Schema.STRING,
            _('The HTTP method used for requests by the monitor of type '
              'HTTP.'),
            update_allowed=True,
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
                constraints.CustomConstraint('octavia.pool')
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
                constraints.AllowedValues(['PING', 'TCP', 'HTTP', 'HTTPS',
                                           'UDP-CONNECT']),
            ]
        ),
        URL_PATH: properties.Schema(
            properties.Schema.STRING,
            _('The HTTP path used in the HTTP request used by the monitor to '
              'test a member health. A valid value is a string the begins '
              'with a forward slash (/).'),
            update_allowed=True,
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

    def translation_rules(self, props):
        return [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                [self.POOL],
                client_plugin=self.client_plugin(),
                finder='get_pool',
            ),
        ]

    def _prepare_args(self, properties):
        props = dict((k, v) for k, v in properties.items() if v is not None)
        if self.POOL in props:
            props['pool_id'] = props.pop(self.POOL)
        return props

    def _resource_create(self, properties):
        return self.client().health_monitor_create(
            json={'healthmonitor': properties})['healthmonitor']

    def _resource_update(self, prop_diff):
        self.client().health_monitor_set(
            self.resource_id, json={'healthmonitor': prop_diff})

    def _resource_delete(self):
        self.client().health_monitor_delete(self.resource_id)

    def _show_resource(self):
        return self.client().health_monitor_show(self.resource_id)


def resource_mapping():
    return {
        'OS::Octavia::HealthMonitor': HealthMonitor,
    }
