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
import six
import webob.exc

import heat.api.middleware.fault as fault
import heat.api.openstack.v1.actions as actions
from heat.common import identifier
from heat.common import policy
from heat.rpc import client as rpc_client
from heat.tests.api.openstack_v1 import tools
from heat.tests import common


@mock.patch.object(policy.Enforcer, 'enforce')
class ActionControllerTest(tools.ControllerTest, common.HeatTestCase):
    """Tests the API class ActionController.

    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    """

    def setUp(self):
        super(ActionControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig(object):
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = actions.ActionController(options=cfgopts)

    def test_action_suspend(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_suspend', {'stack_identity': stack_identity})
        ).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertIsNone(result)
        self.m.VerifyAll()

    def test_action_resume(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'resume': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_resume', {'stack_identity': stack_identity})
        ).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertIsNone(result)
        self.m.VerifyAll()

    def test_action_cancel_update(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'cancel_update': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_cancel_update',
             {'stack_identity': stack_identity,
              'cancel_with_rollback': True}),
            version='1.14'
        ).AndReturn(None)
        self.m.ReplayAll()

        result = self.controller.action(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        body=body)
        self.assertIsNone(result)
        self.m.VerifyAll()

    def test_action_badaction(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'notallowed': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_action_badaction_empty(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_action_badaction_multiple(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'one': None, 'two': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()

    def test_action_rmt_aterr(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            req.context,
            ('stack_suspend', {'stack_identity': stack_identity})
        ).AndRaise(tools.to_remote_error(AttributeError()))
        self.m.ReplayAll()

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.action,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            body=body)

        self.assertEqual(400, resp.json['code'])
        self.assertEqual('AttributeError', resp.json['error']['type'])
        self.m.VerifyAll()

    def test_action_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', False)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'suspend': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.action,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            body=body)
        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_action_badaction_ise(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'action', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        body = {'oops': None}
        req = self._post(stack_identity._tenant_path() + '/actions',
                         data=json.dumps(body))

        self.m.ReplayAll()

        self.controller.ACTIONS = (SUSPEND, NEW) = ('suspend', 'oops')

        self.assertRaises(webob.exc.HTTPInternalServerError,
                          self.controller.action,
                          req, tenant_id=self.tenant,
                          stack_name=stack_identity.stack_name,
                          stack_id=stack_identity.stack_id,
                          body=body)
        self.m.VerifyAll()
