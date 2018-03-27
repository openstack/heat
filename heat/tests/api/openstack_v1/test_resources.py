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
import webob.exc

import heat.api.middleware.fault as fault
import heat.api.openstack.v1.resources as resources
from heat.common import exception as heat_exc
from heat.common import identifier
from heat.common import policy
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client
from heat.tests.api.openstack_v1 import tools
from heat.tests import common


@mock.patch.object(policy.Enforcer, 'enforce')
class ResourceControllerTest(tools.ControllerTest, common.HeatTestCase):
    """Tests the API class ResourceController.

    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    """

    def setUp(self):
        super(ResourceControllerTest, self).setUp()
        # Create WSGI controller instance

        class DummyConfig(object):
            bind_port = 8004

        cfgopts = DummyConfig()
        self.controller = resources.ResourceController(options=cfgopts)

    def test_index(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(stack_identity._tenant_path() + '/resources')

        engine_resp = [
            {
                u'resource_identity': dict(res_identity),
                u'stack_name': stack_identity.stack_name,
                u'resource_name': res_name,
                u'resource_status_reason': None,
                u'updated_time': u'2012-07-23T13:06:00Z',
                u'stack_identity': stack_identity,
                u'resource_action': u'CREATE',
                u'resource_status': u'COMPLETE',
                u'physical_resource_id':
                u'a3455d8c-9f88-404d-a85b-5315293e67de',
                u'resource_type': u'AWS::EC2::Instance',
            }
        ]
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_resp)

        result = self.controller.index(req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        expected = {
            'resources': [{'links': [{'href': self._url(res_identity),
                                      'rel': 'self'},
                                     {'href': self._url(stack_identity),
                                      'rel': 'stack'}],
                           u'resource_name': res_name,
                           u'logical_resource_id': res_name,
                           u'resource_status_reason': None,
                           u'updated_time': u'2012-07-23T13:06:00Z',
                           u'resource_status': u'CREATE_COMPLETE',
                           u'physical_resource_id':
                           u'a3455d8c-9f88-404d-a85b-5315293e67de',
                           u'resource_type': u'AWS::EC2::Instance'}]}
        self.assertEqual(expected, result)

        mock_call.assert_called_once_with(
            req.context,
            ('list_stack_resources', {'stack_identity': stack_identity,
                                      'nested_depth': 0,
                                      'with_detail': False,
                                      'filters': {}
                                      }),
            version='1.25'
        )

    def test_index_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources')

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.index,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('list_stack_resources', {'stack_identity': stack_identity,
                                      'nested_depth': 0,
                                      'with_detail': False,
                                      'filters': {}}),
            version='1.25'
        )

    def test_index_invalid_filters(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources',
                        {'invalid_key': 'junk'})

        mock_call = self.patchobject(rpc_client.EngineClient, 'call')
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.index, req,
                               tenant_id=self.tenant,
                               stack_name=stack_identity.stack_name,
                               stack_id=stack_identity.stack_id)

        self.assertIn("Invalid filter parameters %s" %
                      [six.text_type('invalid_key')],
                      six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_index_nested_depth(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources',
                        {'nested_depth': '99'})

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=[])

        result = self.controller.index(req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        self.assertEqual([], result['resources'])
        mock_call.assert_called_once_with(
            req.context,
            ('list_stack_resources', {'stack_identity': stack_identity,
                                      'nested_depth': 99,
                                      'with_detail': False,
                                      'filters': {}}),
            version='1.25'
        )

    def test_index_nested_depth_not_int(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')

        req = self._get(stack_identity._tenant_path() + '/resources',
                        {'nested_depth': 'non-int'})

        mock_call = self.patchobject(rpc_client.EngineClient, 'call')
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.index, req,
                               tenant_id=self.tenant,
                               stack_name=stack_identity.stack_name,
                               stack_id=stack_identity.stack_id)

        self.assertEqual("Only integer is acceptable by 'nested_depth'.",
                         six.text_type(ex))
        self.assertFalse(mock_call.called)

    def test_index_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', False)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        identifier.ResourceIdentifier(resource_name=res_name,
                                      **stack_identity)

        req = self._get(stack_identity._tenant_path() + '/resources')

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.index,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_index_detail(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'index', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(stack_identity._tenant_path() + '/resources',
                        {'with_detail': 'true'})

        resp_parameters = {
            "OS::project_id": "3ab5b02fa01f4f95afa1e254afc4a435",
            "network": "cf05086d-07c7-4ed6-95e5-e4af724677e6",
            "OS::stack_name": "s1", "admin_pass": "******",
            "key_name": "kk", "image": "fa5d387e-541f-4dfb-ae8a-83a614683f84",
            "db_port": "50000",
            "OS::stack_id": "723d7cee-46b3-4433-9c21-f3378eb0bfc4",
            "flavor": "1"
        },

        engine_resp = [
            {
                u'resource_identity': dict(res_identity),
                u'stack_name': stack_identity.stack_name,
                u'resource_name': res_name,
                u'resource_status_reason': None,
                u'updated_time': u'2012-07-23T13:06:00Z',
                u'stack_identity': stack_identity,
                u'resource_action': u'CREATE',
                u'resource_status': u'COMPLETE',
                u'physical_resource_id':
                u'a3455d8c-9f88-404d-a85b-5315293e67de',
                u'resource_type': u'AWS::EC2::Instance',
                u'parameters': resp_parameters,
                u'description': u'Hello description',
                u'stack_user_project_id': u'6f38bcfebbc4400b82d50c1a2ea3057d',
            }
        ]
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_resp)

        result = self.controller.index(req, tenant_id=self.tenant,
                                       stack_name=stack_identity.stack_name,
                                       stack_id=stack_identity.stack_id)

        expected = {
            'resources': [{'links': [{'href': self._url(res_identity),
                                      'rel': 'self'},
                                     {'href': self._url(stack_identity),
                                      'rel': 'stack'}],
                           u'resource_name': res_name,
                           u'logical_resource_id': res_name,
                           u'resource_status_reason': None,
                           u'updated_time': u'2012-07-23T13:06:00Z',
                           u'resource_status': u'CREATE_COMPLETE',
                           u'physical_resource_id':
                           u'a3455d8c-9f88-404d-a85b-5315293e67de',
                           u'resource_type': u'AWS::EC2::Instance',
                           u'parameters': resp_parameters,
                           u'description': u'Hello description',
                           u'stack_user_project_id':
                           u'6f38bcfebbc4400b82d50c1a2ea3057d'}]}
        self.assertEqual(expected, result)

        mock_call.assert_called_once_with(
            req.context,
            ('list_stack_resources', {'stack_identity': stack_identity,
                                      'nested_depth': 0,
                                      'with_detail': True,
                                      'filters': {}}),
            version='1.25'
        )

    def test_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(stack_identity._tenant_path())

        engine_resp = {
            u'description': u'',
            u'resource_identity': dict(res_identity),
            u'stack_name': stack_identity.stack_name,
            u'resource_name': res_name,
            u'resource_status_reason': None,
            u'updated_time': u'2012-07-23T13:06:00Z',
            u'stack_identity': dict(stack_identity),
            u'resource_action': u'CREATE',
            u'resource_status': u'COMPLETE',
            u'physical_resource_id':
            u'a3455d8c-9f88-404d-a85b-5315293e67de',
            u'resource_type': u'AWS::EC2::Instance',
            u'attributes': {u'foo': 'bar'},
            u'metadata': {u'ensureRunning': u'true'}
        }
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_resp)

        result = self.controller.show(req, tenant_id=self.tenant,
                                      stack_name=stack_identity.stack_name,
                                      stack_id=stack_identity.stack_id,
                                      resource_name=res_name)

        expected = {
            'resource': {
                'links': [
                    {'href': self._url(res_identity), 'rel': 'self'},
                    {'href': self._url(stack_identity), 'rel': 'stack'},
                ],
                u'description': u'',
                u'resource_name': res_name,
                u'logical_resource_id': res_name,
                u'resource_status_reason': None,
                u'updated_time': u'2012-07-23T13:06:00Z',
                u'resource_status': u'CREATE_COMPLETE',
                u'physical_resource_id':
                u'a3455d8c-9f88-404d-a85b-5315293e67de',
                u'resource_type': u'AWS::EC2::Instance',
                u'attributes': {u'foo': 'bar'},
            }
        }
        self.assertEqual(expected, result)

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        )

    def test_show_with_nested_stack(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        nested_stack_identity = identifier.HeatIdentifier(self.tenant,
                                                          'nested', 'some_id')

        req = self._get(stack_identity._tenant_path())

        engine_resp = {
            u'description': u'',
            u'resource_identity': dict(res_identity),
            u'stack_name': stack_identity.stack_name,
            u'resource_name': res_name,
            u'resource_status_reason': None,
            u'updated_time': u'2012-07-23T13:06:00Z',
            u'stack_identity': dict(stack_identity),
            u'resource_action': u'CREATE',
            u'resource_status': u'COMPLETE',
            u'physical_resource_id':
            u'a3455d8c-9f88-404d-a85b-5315293e67de',
            u'resource_type': u'AWS::EC2::Instance',
            u'attributes': {u'foo': 'bar'},
            u'metadata': {u'ensureRunning': u'true'},
            u'nested_stack_id': dict(nested_stack_identity)
        }
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_resp)

        result = self.controller.show(req, tenant_id=self.tenant,
                                      stack_name=stack_identity.stack_name,
                                      stack_id=stack_identity.stack_id,
                                      resource_name=res_name)

        expected = [{'href': self._url(res_identity), 'rel': 'self'},
                    {'href': self._url(stack_identity), 'rel': 'stack'},
                    {'href': self._url(nested_stack_identity), 'rel': 'nested'}
                    ]
        self.assertEqual(expected, result['resource']['links'])
        self.assertIsNone(result.get(rpc_api.RES_NESTED_STACK_ID))

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        )

    def test_show_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.show,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        )

    def test_show_with_single_attribute(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant, 'foo', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        mock_describe = mock.Mock(return_value={'foo': 'bar'})
        self.controller.rpc_client.describe_stack_resource = mock_describe

        req = self._get(res_identity._tenant_path(), {'with_attr': 'baz'})
        resp = self.controller.show(req, tenant_id=self.tenant,
                                    stack_name=stack_identity.stack_name,
                                    stack_id=stack_identity.stack_id,
                                    resource_name=res_name)

        self.assertEqual({'resource': {'foo': 'bar'}}, resp)
        args, kwargs = mock_describe.call_args
        self.assertIn('baz', kwargs['with_attr'])

    def test_show_with_multiple_attributes(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant, 'foo', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)
        mock_describe = mock.Mock(return_value={'foo': 'bar'})
        self.controller.rpc_client.describe_stack_resource = mock_describe

        req = self._get(res_identity._tenant_path())
        req.environ['QUERY_STRING'] = 'with_attr=a1&with_attr=a2&with_attr=a3'
        resp = self.controller.show(req, tenant_id=self.tenant,
                                    stack_name=stack_identity.stack_name,
                                    stack_id=stack_identity.stack_id,
                                    resource_name=res_name)

        self.assertEqual({'resource': {'foo': 'bar'}}, resp)
        args, kwargs = mock_describe.call_args
        self.assertIn('a1', kwargs['with_attr'])
        self.assertIn('a2', kwargs['with_attr'])
        self.assertIn('a3', kwargs['with_attr'])

    def test_show_nonexist_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'Wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.ResourceNotFound(stack_name='a', resource_name='b')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.show,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        )

    def test_show_uncreated_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        error = heat_exc.ResourceNotAvailable(resource_name='')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.show,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceNotAvailable', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': None}),
            version='1.2'
        )

    def test_show_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'show', False)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path())

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.show,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_metadata_show(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(stack_identity._tenant_path())

        engine_resp = {
            u'description': u'',
            u'resource_identity': dict(res_identity),
            u'stack_name': stack_identity.stack_name,
            u'resource_name': res_name,
            u'resource_status_reason': None,
            u'updated_time': u'2012-07-23T13:06:00Z',
            u'stack_identity': dict(stack_identity),
            u'resource_action': u'CREATE',
            u'resource_status': u'COMPLETE',
            u'physical_resource_id':
            u'a3455d8c-9f88-404d-a85b-5315293e67de',
            u'resource_type': u'AWS::EC2::Instance',
            u'metadata': {u'ensureRunning': u'true'}
        }
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=engine_resp)

        result = self.controller.metadata(req, tenant_id=self.tenant,
                                          stack_name=stack_identity.stack_name,
                                          stack_id=stack_identity.stack_id,
                                          resource_name=res_name)

        expected = {'metadata': {u'ensureRunning': u'true'}}
        self.assertEqual(expected, result)

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': False}),
            version='1.2'
        )

    def test_metadata_show_nonexist(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'rubbish', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        error = heat_exc.EntityNotFound(entity='Stack', name='a')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.metadata,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('EntityNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': False}),
            version='1.2'
        )

    def test_metadata_show_nonexist_resource(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', True)
        res_name = 'wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        error = heat_exc.ResourceNotFound(stack_name='a', resource_name='b')
        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     side_effect=tools.to_remote_error(error))

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.metadata,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name)

        self.assertEqual(404, resp.json['code'])
        self.assertEqual('ResourceNotFound', resp.json['error']['type'])

        mock_call.assert_called_once_with(
            req.context,
            ('describe_stack_resource',
             {'stack_identity': stack_identity, 'resource_name': res_name,
              'with_attr': False}),
            version='1.2'
        )

    def test_metadata_show_err_denied_policy(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'metadata', False)
        res_name = 'wibble'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')
        res_identity = identifier.ResourceIdentifier(resource_name=res_name,
                                                     **stack_identity)

        req = self._get(res_identity._tenant_path() + '/metadata')

        resp = tools.request_with_middleware(
            fault.FaultWrapper,
            self.controller.metadata,
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name)

        self.assertEqual(403, resp.status_int)
        self.assertIn('403 Forbidden', six.text_type(resp))

    def test_signal(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'signal', True)
        res_name = 'WikiDatabase'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '6')

        req = self._get(stack_identity._tenant_path())

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=None)

        result = self.controller.signal(req, tenant_id=self.tenant,
                                        stack_name=stack_identity.stack_name,
                                        stack_id=stack_identity.stack_id,
                                        resource_name=res_name,
                                        body="Signal content")

        self.assertIsNone(result)

        mock_call.assert_called_once_with(
            req.context,
            ('resource_signal', {'stack_identity': stack_identity,
                                 'resource_name': res_name,
                                 'details': 'Signal content',
                                 'sync_call': False}),
            version='1.3'
        )

    def test_mark_unhealthy_valid_request(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'mark_unhealthy', True)
        res_name = 'WebServer'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')

        req = self._get(stack_identity._tenant_path())

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=None)
        body = {'mark_unhealthy': True,
                rpc_api.RES_STATUS_DATA: 'Anything'}
        params = {'stack_identity': stack_identity,
                  'resource_name': res_name}
        params.update(body)

        result = self.controller.mark_unhealthy(
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name,
            body=body)

        self.assertIsNone(result)

        mock_call.assert_called_once_with(
            req.context,
            ('resource_mark_unhealthy', params),
            version='1.26'
        )

    def test_mark_unhealthy_without_reason(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'mark_unhealthy', True)
        res_name = 'WebServer'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')

        req = self._get(stack_identity._tenant_path())

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=None)
        body = {'mark_unhealthy': True, rpc_api.RES_STATUS_DATA: ''}
        params = {'stack_identity': stack_identity,
                  'resource_name': res_name}
        params.update(body)

        del body[rpc_api.RES_STATUS_DATA]

        result = self.controller.mark_unhealthy(
            req, tenant_id=self.tenant,
            stack_name=stack_identity.stack_name,
            stack_id=stack_identity.stack_id,
            resource_name=res_name,
            body=body)

        self.assertIsNone(result)

        mock_call.assert_called_once_with(
            req.context,
            ('resource_mark_unhealthy', params),
            version='1.26'
        )

    def test_mark_unhealthy_with_invalid_keys(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'mark_unhealthy', True)
        res_name = 'WebServer'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')

        req = self._get(stack_identity._tenant_path())

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=None)
        body = {'mark_unhealthy': True,
                rpc_api.RES_STATUS_DATA: 'Any',
                'invalid_key1': 1, 'invalid_key2': 2}
        expected = "Invalid keys in resource mark unhealthy"
        actual = self.assertRaises(webob.exc.HTTPBadRequest,
                                   self.controller.mark_unhealthy, req,
                                   tenant_id=self.tenant,
                                   stack_name=stack_identity.stack_name,
                                   stack_id=stack_identity.stack_id,
                                   resource_name=res_name,
                                   body=body)

        self.assertIn(expected, six.text_type(actual))
        self.assertIn('invalid_key1', six.text_type(actual))
        self.assertIn('invalid_key2', six.text_type(actual))
        mock_call.assert_not_called()

    def test_mark_unhealthy_with_invalid_value(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'mark_unhealthy', True)
        res_name = 'WebServer'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')

        req = self._get(stack_identity._tenant_path())

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=None)
        body = {'mark_unhealthy': 'XYZ',
                rpc_api.RES_STATUS_DATA: 'Any'}

        expected = ('Unrecognized value "XYZ" for "mark_unhealthy", '
                    'acceptable values are: true, false')

        actual = self.assertRaises(webob.exc.HTTPBadRequest,
                                   self.controller.mark_unhealthy, req,
                                   tenant_id=self.tenant,
                                   stack_name=stack_identity.stack_name,
                                   stack_id=stack_identity.stack_id,
                                   resource_name=res_name,
                                   body=body)

        self.assertIn(expected, six.text_type(actual))
        mock_call.assert_not_called()

    def test_mark_unhealthy_without_mark_unhealthy_key(self, mock_enforce):
        self._mock_enforce_setup(mock_enforce, 'mark_unhealthy', True)
        res_name = 'WebServer'
        stack_identity = identifier.HeatIdentifier(self.tenant,
                                                   'wordpress', '1')

        req = self._get(stack_identity._tenant_path())

        mock_call = self.patchobject(rpc_client.EngineClient, 'call',
                                     return_value=None)
        body = {rpc_api.RES_STATUS_DATA: 'Any'}

        expected = ("Missing mandatory (%s) key from "
                    "mark unhealthy request" % 'mark_unhealthy')

        actual = self.assertRaises(webob.exc.HTTPBadRequest,
                                   self.controller.mark_unhealthy, req,
                                   tenant_id=self.tenant,
                                   stack_name=stack_identity.stack_name,
                                   stack_id=stack_identity.stack_id,
                                   resource_name=res_name,
                                   body=body)

        self.assertIn(expected, six.text_type(actual))
        mock_call.assert_not_called()
