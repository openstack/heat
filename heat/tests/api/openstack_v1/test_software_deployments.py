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
import heat.api.openstack.v1.software_deployments as software_deployments
from heat.common import exception as heat_exc
from heat.common import policy
from heat.tests.api.openstack_v1 import tools
from heat.tests import common


class SoftwareDeploymentControllerTest(tools.ControllerTest,
                                       common.HeatTestCase):

    def setUp(self):
        super(SoftwareDeploymentControllerTest, self).setUp()
        self.controller = software_deployments.SoftwareDeploymentController({})

    def test_default(self):
        self.assertRaises(
            webob.exc.HTTPNotFound, self.controller.default, None)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_index(self, mock_enforce):
        self._mock_enforce_setup(
            mock_enforce, 'index', expected_request_count=2)
        req = self._get('/software_deployments')
        return_value = []
        with mock.patch.object(
                self.controller.rpc_client,
                'list_software_deployments',
                return_value=return_value) as mock_call:
            resp = self.controller.index(req, tenant_id=self.tenant)
            self.assertEqual(
                {'software_deployments': []}, resp)
            whitelist = mock_call.call_args[1]
            self.assertEqual({}, whitelist)
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        req = self._get('/software_deployments', {'server_id': server_id})
        with mock.patch.object(
                self.controller.rpc_client,
                'list_software_deployments',
                return_value=return_value) as mock_call:
            resp = self.controller.index(req, tenant_id=self.tenant)
            self.assertEqual(
                {'software_deployments': []}, resp)
            whitelist = mock_call.call_args[1]
            self.assertEqual({'server_id': server_id}, whitelist)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        deployment_id = '38eccf10-97e5-4ae8-9d37-b577c9801750'
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        req = self._get('/software_deployments/%s' % deployment_id)
        return_value = {
            'id': deployment_id,
            'server_id': server_id,
            'input_values': {},
            'output_values': {},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id,
            'config': '#!/bin/bash',
            'name': 'config_mysql',
            'group': 'Heat::Shell',
            'inputs': [],
            'outputs': [],
            'options': []}

        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_deployment',
                return_value=return_value):
            resp = self.controller.show(
                req, deployment_id=config_id, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_show_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show')
        deployment_id = '38eccf10-97e5-4ae8-9d37-b577c9801750'
        req = self._get('/software_deployments/%s' % deployment_id)

        error = heat_exc.NotFound('Not found %s' % deployment_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'show_software_deployment',
                side_effect=tools.to_remote_error(error)):
            resp = tools.request_with_middleware(
                fault.FaultWrapper, self.controller.show,
                req, deployment_id=deployment_id, tenant_id=self.tenant)

            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_create(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'create')
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        body = {
            'server_id': server_id,
            'input_values': {},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id}
        return_value = body.copy()
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = deployment_id
        req = self._post('/software_deployments', json.dumps(body))

        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'create_software_deployment',
                return_value=return_value):
            resp = self.controller.create(
                req, body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_update(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update')
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        body = {
            'input_values': {},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id}
        return_value = body.copy()
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = deployment_id
        req = self._put('/software_deployments/%s' % deployment_id,
                        json.dumps(body))
        return_value['server_id'] = server_id
        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'update_software_deployment',
                return_value=return_value):
            resp = self.controller.update(
                req, deployment_id=deployment_id,
                body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_update_no_input_values(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update')
        config_id = 'd00ba4aa-db33-42e1-92f4-2a6469260107'
        server_id = 'fb322564-7927-473d-8aad-68ae7fbf2abf'
        body = {
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': None,
            'config_id': config_id}
        return_value = body.copy()
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        return_value['id'] = deployment_id
        req = self._put('/software_deployments/%s' % deployment_id,
                        json.dumps(body))
        return_value['server_id'] = server_id
        expected = {'software_deployment': return_value}
        with mock.patch.object(
                self.controller.rpc_client,
                'update_software_deployment',
                return_value=return_value):
            resp = self.controller.update(
                req, deployment_id=deployment_id,
                body=body, tenant_id=self.tenant)
            self.assertEqual(expected, resp)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_update_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'update')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._put('/software_deployments/%s' % deployment_id,
                        '{}')
        error = heat_exc.NotFound('Not found %s' % deployment_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'update_software_deployment',
                side_effect=tools.to_remote_error(error)):
            resp = tools.request_with_middleware(
                fault.FaultWrapper, self.controller.update,
                req, deployment_id=deployment_id,
                body={}, tenant_id=self.tenant)
            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_deployments/%s' % deployment_id)
        return_value = None
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_deployment',
                return_value=return_value):
            self.assertRaises(
                webob.exc.HTTPNoContent, self.controller.delete,
                req, deployment_id=deployment_id, tenant_id=self.tenant)

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_error(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_deployments/%s' % deployment_id)
        error = Exception('something wrong')
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_deployment',
                side_effect=tools.to_remote_error(error)):
            resp = tools.request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, deployment_id=deployment_id, tenant_id=self.tenant)
            self.assertEqual(500, resp.json['code'])
            self.assertEqual('Exception', resp.json['error']['type'])

    @mock.patch.object(policy.Enforcer, 'enforce')
    def test_delete_not_found(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'delete')
        deployment_id = 'a45559cd-8736-4375-bc39-d6a7bb62ade2'
        req = self._delete('/software_deployments/%s' % deployment_id)
        error = heat_exc.NotFound('Not Found %s' % deployment_id)
        with mock.patch.object(
                self.controller.rpc_client,
                'delete_software_deployment',
                side_effect=tools.to_remote_error(error)):
            resp = tools.request_with_middleware(
                fault.FaultWrapper, self.controller.delete,
                req, deployment_id=deployment_id, tenant_id=self.tenant)
            self.assertEqual(404, resp.json['code'])
            self.assertEqual('NotFound', resp.json['error']['type'])
