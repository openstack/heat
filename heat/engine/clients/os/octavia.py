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

from octaviaclient.api import constants
from octaviaclient.api.v2 import octavia
from osc_lib import exceptions

from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'octavia'
DEFAULT_FIND_ATTR = 'name'


def _is_translated_exception(ex, code):
    return (isinstance(ex, octavia.OctaviaClientException)
            and ex.code == code)


class OctaviaClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = octavia

    service_types = [LOADBALANCER] = ['load-balancer']

    supported_versions = [V2] = ['2']

    default_version = V2

    def _create(self, version=None):
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        endpoint = self.url_for(service_type=self.LOADBALANCER,
                                endpoint_type=interface)
        return octavia.OctaviaAPI(
            session=self.context.keystone_session,
            service_type=self.LOADBALANCER,
            endpoint=endpoint)

    def is_not_found(self, ex):
        return isinstance(
            ex, exceptions.NotFound) or _is_translated_exception(ex, 404)

    def is_over_limit(self, ex):
        return isinstance(
            ex, exceptions.OverLimit) or _is_translated_exception(ex, 413)

    def is_conflict(self, ex):
        return isinstance(
            ex, exceptions.Conflict) or _is_translated_exception(ex, 409)

    def get_pool(self, value):
        pool = self.client().find(path=constants.BASE_POOL_URL,
                                  value=value, attr=DEFAULT_FIND_ATTR)
        return pool['id']

    def get_listener(self, value):
        lsnr = self.client().find(path=constants.BASE_LISTENER_URL,
                                  value=value, attr=DEFAULT_FIND_ATTR)
        return lsnr['id']

    def get_loadbalancer(self, value):
        lb = self.client().find(path=constants.BASE_LOADBALANCER_URL,
                                value=value, attr=DEFAULT_FIND_ATTR)
        return lb['id']

    def get_l7policy(self, value):
        policy = self.client().find(path=constants.BASE_L7POLICY_URL,
                                    value=value, attr=DEFAULT_FIND_ATTR)
        return policy['id']


class OctaviaConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exceptions.NotFound,
                           octavia.OctaviaClientException)
    base_url = None

    def validate_with_client(self, client, value):
        octavia_client = client.client(CLIENT_NAME)
        octavia_client.find(path=self.base_url, value=value,
                            attr=DEFAULT_FIND_ATTR)


class LoadbalancerConstraint(OctaviaConstraint):
    base_url = constants.BASE_LOADBALANCER_URL


class ListenerConstraint(OctaviaConstraint):
    base_url = constants.BASE_LISTENER_URL


class PoolConstraint(OctaviaConstraint):
    base_url = constants.BASE_POOL_URL


class L7PolicyConstraint(OctaviaConstraint):
    base_url = constants.BASE_L7POLICY_URL
