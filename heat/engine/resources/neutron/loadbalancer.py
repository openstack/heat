# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.engine import clients
from heat.engine import scheduler
from heat.engine.resources.neutron import neutron

if clients.neutronclient is not None:
    from neutronclient.common.exceptions import NeutronClientException


class HealthMonitor(neutron.NeutronResource):
    """
    A resource for managing health monitors for load balancers in Neutron.
    """

    properties_schema = {
        'delay': {'Type': 'Integer', 'Required': True},
        'type': {'Type': 'String', 'Required': True,
                 'AllowedValues': ['PING', 'TCP', 'HTTP', 'HTTPS']},
        'max_retries': {'Type': 'Integer', 'Required': True},
        'timeout': {'Type': 'Integer', 'Required': True},
        'admin_state_up': {'Default': True, 'Type': 'Boolean'},
        'http_method': {'Type': 'String'},
        'expected_codes': {'Type': 'String'},
        'url_path': {'Type': 'String'},
    }

    update_allowed_keys = ('Properties',)
    update_allowed_properties = ('delay', 'max_retries', 'timeout',
                                 'admin_state_up', 'http_method',
                                 'expected_codes', 'url_path')

    attributes_schema = {
        'admin_state_up': 'the administrative state of this port',
        'delay': 'the minimum time in seconds between regular connections '
                 'of the member',
        'expected_codes': 'the list of HTTP status codes expected in '
                          'response from the member to declare it healthy',
        'http_method': 'the HTTP method used for requests by the monitor of '
                       'type HTTP',
        'id': 'unique identifier for this health monitor',
        'max_retries': 'number of permissible connection failures before '
                       'changing the member status to INACTIVE.',
        'timeout': 'maximum number of seconds for a monitor to wait for a '
                   'connection to be established before it times out',
        'type': 'one of predefined health monitor types',
        'url_path': 'the HTTP path used in the HTTP request used by the '
                    'monitor to test a member health',
        'tenant_id': 'tenant owning the health monitor',
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
        self.neutron().update_health_monitor(
            self.resource_id, {'health_monitor': prop_diff})

    def handle_delete(self):
        try:
            self.neutron().delete_health_monitor(self.resource_id)
        except NeutronClientException as ex:
            if ex.status_code != 404:
                raise ex
        else:
            return scheduler.TaskRunner(self._confirm_delete)()


def resource_mapping():
    if clients.neutronclient is None:
        return {}

    return {
        'OS::Neutron::HealthMonitor': HealthMonitor,
    }
