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

import json

import mock
import webob.exc

import heat.api.middleware.fault as fault
import heat.api.openstack.v1.software_configs as software_configs
from heat.common import exception as heat_exc
from heat.common import policy
from heat.tests.api.openstack_v1 import tools
from heat.tests import common


class SoftwareConfigControllerTest(tools.ControllerTest, common.HeatTestCase):

    def setUp(self):
        super(SoftwareConfigControllerTest, self).setUp()
        self.controller = software_configs.SoftwareConfigController({})

    def test_default(self):
        self.assertRaises(
            webob.exc.HTTPNotFound, self.controller.default, None)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_index(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index')
        req = self._get('/software_configs')
        with mock.patch.object(
                self.controller.rpc_client,
                'list_software_configs',
                return_value=[]):
            resp = self.controller.index(req, tenant_id=self.tenant)
            self.assertEqual(
                {'software_configs': []}, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._get('/software_configs/%s' % config_id)
        return_value = {
            'id': config_id,
            'name': 'config_mysql',
            'group': 'Heat::Shell',
            'config': '#!/bin/bash',
            'inputs': [],
            'ouputs': [],
            'options': []}

        expected = {'software_config': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_config',
                return_value=return_value):
            resp = self.controller.show(
                req, config_id=config_id, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._get('/software_configs/%s' % config_id)

        error = heat_exc.NotFound('Not found %s' % config_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_config',
                side_effect=tools.to_remote_error(error)):
            resp = tools.request_with_middleware(fault.FaultWrapper,
                                                 self.controller.show,
                                                 req, config_id=config_id,
                                                 tenant_id=self.tenant)
            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_create(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create')
        body = {
            'name': 'config_mysql',
            'group': 'Heat::Shell',
            'config': '#!/bin/bash',
            'inputs': [],
            'ouputs': [],
            'options': []}
        return_value = body.copy()
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = config_id
        req = self._post('/software_configs', json.dumps(body))

        expected = {'software_config': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'create_software_config',
                return_value=return_value):
            resp = self.controller.create(
                req, body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_configs/%s' % config_id)
        return_value = None
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_config',
                return_value=return_value):
            self.assertRaises(
                webob.exc.HTTPNoContent, self.controller.delete,
                req, config_id=config_id, tenant_id=self.tenant)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_configs/%s' % config_id)
        error = Exception('something wrong')
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_config',
                side_effect=tools.to_remote_error(error)):
            resp = tools.request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, config_id=config_id, tenant_id=self.tenant)

            self.assertEqual(500, resp.json['code'])
            self.assertEqual('Exception', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        config_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_configs/%s' % config_id)
        error = heat_exc.NotFound('Not found %s' % config_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_config',
                side_effect=tools.to_remote_error(error)):
            resp = tools.request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, config_id=config_id, tenant_id=self.tenant)

            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])
