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
import six

import heat.api.middleware.fault as fault
import heat.api.openstack.v1.build_info as build_info
from heat.common import policy
from heat.tests.api.openstack_v1 import tools
from heat.tests import common


@mock.patch.object(policy.Enforcer, 'enforce')
class BuildInfoControllerTest(tools.ControllerTest, common.HeatTestCase):

    def setUp(self):
        super(BuildInfoControllerTest, self).setUp()
        self.controller = build_info.BuildInfoController({})

    def test_theres_a_default_api_build_revision(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', True)
        req = self._get('/build_info')
        self.controller.rpc_client = mock.Mock()

        response = self.controller.build_info(req, tenant_id=self.tenant)
        self.assertIn('api', response)
        self.assertIn('revision', response['api'])
        self.assertEqual('unknown', response['api']['revision'])

    @mock.patch.object(build_info.cfg, 'CONF')
    def test_response_api_build_revision_from_config_file(
            self, mock_conf, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', True)
        req = self._get('/build_info')
        mock_engine = mock.Mock()
        mock_engine.get_revision.return_value = 'engine_revision'
        self.controller.rpc_client = mock_engine
        mock_conf.revision = {'heat_revision': 'test'}

        response = self.controller.build_info(req, tenant_id=self.tenant)
        self.assertEqual('test', response['api']['revision'])

    def test_retrieves_build_revision_from_the_engine(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', True)
        req = self._get('/build_info')
        mock_engine = mock.Mock()
        mock_engine.get_revision.return_value = 'engine_revision'
        self.controller.rpc_client = mock_engine

        response = self.controller.build_info(req, tenant_id=self.tenant)
        self.assertIn('engine', response)
        self.assertIn('revision', response['engine'])
        self.assertEqual('engine_revision', response['engine']['revision'])

    def test_build_info_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'build_info', False)
        req = self._get('/build_info')

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.build_info,
            req, tenant_id=self.tenant)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))
