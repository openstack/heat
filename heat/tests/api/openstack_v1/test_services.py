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

import mock
from oslo_messaging import exceptions
import webob.exc

import heat.api.openstack.v1.services as services
from heat.common import policy
from heat.tests.api.openstack_v1 import tools
from heat.tests import common


class ServiceControllerTest(tools.ControllerTest, common.HeatTestCase):

    def setUp(self):
        super(ServiceControllerTest, self).setUp()
        self.controller = services.ServiceController({})

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_index(self, mock_enforce):
        self._mock_enforce_setup(
            mock_enforce, 'index')
        req = self._get('/services')
        return_value = []
        with mock.patch.object(
                self.controller.rpc_client,
                'list_services',
                return_value=return_value):
            resp = self.controller.index(req, tenant_id=self.tenant)
            self.assertEqual(
                {'services': []}, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_index_503(self, mock_enforce):
        self._mock_enforce_setup(
            mock_enforce, 'index')
        req = self._get('/services')
        with mock.patch.object(
                self.controller.rpc_client,
                'list_services',
                side_effect=exceptions.MessagingTimeout()):
            self.assertRaises(
                webob.exc.HTTPServiceUnavailable,
                self.controller.index, req, tenant_id=self.tenant)
