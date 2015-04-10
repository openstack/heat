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
import os

import mock
from oslo_config import cfg
import six

from heat.api.aws import exception
import heat.api.cfn.v1.stacks as stacks
from heat.common import exception as heat_exception
from heat.common import identifier
from heat.common import policy
from heat.common import wsgi
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client
from heat.tests import common
from heat.tests import utils

policy_path = os.path.dirname(os.path.realpath(__file__)) + "/policy/"


class CfnStackControllerTest(common.HeatTestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''

    def setUp(self):
        super(CfnStackControllerTest, self).setUp()

        opts = [
            cfg.StrOpt('config_dir', default=policy_path),
            cfg.StrOpt('config_file', default='foo'),
            cfg.StrOpt('project', default='heat'),
        ]
        cfg.CONF.register_opts(opts)
        cfg.CONF.set_default('host', 'host')
        self.topic = rpc_api.ENGINE_TOPIC
        self.api_version = '1.0'
        self.template = {u'AWSTemplateFormatVersion': u'2010-09-09',
                         u'Foo': u'bar'}

        # Create WSGI controller instance
        class DummyConfig(object):
            bind_port = 8000
        cfgopts = DummyConfig()
        self.controller = stacks.StackController(options=cfgopts)
        self.controller.policy.enforcer.policy_path = (policy_path +
                                                       'deny_stack_user.json')
        self.addCleanup(self.m.VerifyAll)

    def _dummy_GET_request(self, params=None):
        # Mangle the params dict into a query string
        params = params or {}
        qs = "&".join(["=".join([k, str(params[k])]) for k in params])
        environ = {'REQUEST_METHOD': 'GET', 'QUERY_STRING': qs}
        req = wsgi.Request(environ)
        req.context = utils.dummy_context()
        return req

    def _stub_enforce(self, req, action, allowed=True):
        self.m.StubOutWithMock(policy.Enforcer, 'enforce')
        if allowed:
            policy.Enforcer.enforce(req.context, action
                                    ).AndReturn(True)
        else:
            policy.Enforcer.enforce(req.context, action
                                    ).AndRaise(heat_exception.Forbidden)
        self.m.ReplayAll()

    # The tests
    def test_stackid_addprefix(self):
        self.m.ReplayAll()

        response = self.controller._id_format({
            'StackName': 'Foo',
            'StackId': {
                u'tenant': u't',
                u'stack_name': u'Foo',
                u'stack_id': u'123',
                u'path': u''
            }
        })
        expected = {'StackName': 'Foo',
                    'StackId': 'arn:openstack:heat::t:stacks/Foo/123'}
        self.assertEqual(expected, response)

    def test_enforce_ok(self):
        params = {'Action': 'ListStacks'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ListStacks')
        response = self.controller._enforce(dummy_req, 'ListStacks')
        self.assertIsNone(response)

    def test_enforce_denied(self):
        self.m.ReplayAll()
        params = {'Action': 'ListStacks'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ListStacks', False)
        self.assertRaises(exception.HeatAccessDeniedError,
                          self.controller._enforce, dummy_req, 'ListStacks')

    def test_enforce_ise(self):
        params = {'Action': 'ListStacks'}
        dummy_req = self._dummy_GET_request(params)
        dummy_req.context.roles = ['heat_stack_user']

        self.m.StubOutWithMock(policy.Enforcer, 'enforce')
        policy.Enforcer.enforce(dummy_req.context, 'ListStacks'
                                ).AndRaise(AttributeError)
        self.m.ReplayAll()

        self.assertRaises(exception.HeatInternalFailureError,
                          self.controller._enforce, dummy_req, 'ListStacks')

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_list(self, mock_call):
        # Format a dummy GET request to pass into the WSGI handler
        params = {'Action': 'ListStacks'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ListStacks')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = [{u'stack_identity': {u'tenant': u't',
                                            u'stack_name': u'wordpress',
                                            u'stack_id': u'1',
                                            u'path': u''},
                        u'updated_time': u'2012-07-09T09:13:11Z',
                        u'template_description': u'blah',
                        u'stack_status_reason': u'Stack successfully created',
                        u'creation_time': u'2012-07-09T09:12:45Z',
                        u'stack_name': u'wordpress',
                        u'stack_action': u'CREATE',
                        u'stack_status': u'COMPLETE'}]
        mock_call.return_value = engine_resp

        # Call the list controller function and compare the response
        result = self.controller.list(dummy_req)
        expected = {'ListStacksResponse': {'ListStacksResult':
                    {'StackSummaries':
                     [{u'StackId': u'arn:openstack:heat::t:stacks/wordpress/1',
                       u'LastUpdatedTime': u'2012-07-09T09:13:11Z',
                       u'TemplateDescription': u'blah',
                       u'StackStatusReason': u'Stack successfully created',
                       u'CreationTime': u'2012-07-09T09:12:45Z',
                       u'StackName': u'wordpress',
                       u'StackStatus': u'CREATE_COMPLETE'}]}}}
        self.assertEqual(expected, result)
        default_args = {'limit': None, 'sort_keys': None, 'marker': None,
                        'sort_dir': None, 'filters': None, 'tenant_safe': True,
                        'show_deleted': False, 'show_nested': False,
                        'show_hidden': False}
        mock_call.assert_called_once_with(
            dummy_req.context, ('list_stacks', default_args))

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_list_rmt_aterr(self, mock_call):
        params = {'Action': 'ListStacks'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ListStacks')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        mock_call.side_effect = AttributeError

        # Call the list controller function and compare the response
        result = self.controller.list(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)
        mock_call.assert_called_once_with(
            dummy_req.context, ('list_stacks', mock.ANY))

    @mock.patch.object(rpc_client.EngineClient, 'call')
    def test_list_rmt_interr(self, mock_call):
        params = {'Action': 'ListStacks'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ListStacks')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        mock_call.side_effect = Exception()

        # Call the list controller function and compare the response
        result = self.controller.list(dummy_req)
        self.assertIsInstance(result, exception.HeatInternalFailureError)
        mock_call.assert_called_once_with(
            dummy_req.context, ('list_stacks', mock.ANY))

    def test_describe_last_updated_time(self):
        params = {'Action': 'DescribeStacks'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStacks')

        engine_resp = [{u'updated_time': '1970-01-01',
                        u'parameters': {},
                        u'stack_action': u'CREATE',
                        u'stack_status': u'COMPLETE'}]

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('show_stack', {'stack_identity': None})
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.describe(dummy_req)
        result = response['DescribeStacksResponse']['DescribeStacksResult']
        stack = result['Stacks'][0]
        self.assertEqual('1970-01-01', stack['LastUpdatedTime'])

    def test_describe_no_last_updated_time(self):
        params = {'Action': 'DescribeStacks'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStacks')

        engine_resp = [{u'updated_time': None,
                        u'parameters': {},
                        u'stack_action': u'CREATE',
                        u'stack_status': u'COMPLETE'}]

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('show_stack', {'stack_identity': None})
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.describe(dummy_req)
        result = response['DescribeStacksResponse']['DescribeStacksResult']
        stack = result['Stacks'][0]
        self.assertNotIn('LastUpdatedTime', stack)

    def test_describe(self):
        # Format a dummy GET request to pass into the WSGI handler
        stack_name = u"wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStacks', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStacks')

        # Stub out the RPC call to the engine with a pre-canned response
        # Note the engine returns a load of keys we don't actually use
        # so this is a subset of the real response format
        engine_resp = [{u'stack_identity':
                        {u'tenant': u't',
                         u'stack_name': u'wordpress',
                         u'stack_id': u'6',
                         u'path': u''},
                        u'updated_time': u'2012-07-09T09:13:11Z',
                        u'parameters': {u'DBUsername': u'admin',
                                        u'LinuxDistribution': u'F17',
                                        u'InstanceType': u'm1.large',
                                        u'DBRootPassword': u'admin',
                                        u'DBPassword': u'admin',
                                        u'DBName': u'wordpress'},
                        u'outputs':
                        [{u'output_key': u'WebsiteURL',
                          u'description': u'URL for Wordpress wiki',
                          u'output_value': u'http://10.0.0.8/wordpress'}],
                        u'stack_status_reason': u'Stack successfully created',
                        u'creation_time': u'2012-07-09T09:12:45Z',
                        u'stack_name': u'wordpress',
                        u'notification_topics': [],
                        u'stack_action': u'CREATE',
                        u'stack_status': u'COMPLETE',
                        u'description': u'blah',
                        u'disable_rollback': 'true',
                        u'timeout_mins':60,
                        u'capabilities':[]}]

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('show_stack', {'stack_identity': identity})
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        # Call the list controller function and compare the response
        response = self.controller.describe(dummy_req)

        expected = {'DescribeStacksResponse':
                    {'DescribeStacksResult':
                     {'Stacks':
                      [{'StackId': u'arn:openstack:heat::t:stacks/wordpress/6',
                        'StackStatusReason': u'Stack successfully created',
                        'Description': u'blah',
                        'Parameters':
                        [{'ParameterValue': u'admin',
                          'ParameterKey': u'DBUsername'},
                         {'ParameterValue': u'F17',
                          'ParameterKey': u'LinuxDistribution'},
                         {'ParameterValue': u'm1.large',
                          'ParameterKey': u'InstanceType'},
                         {'ParameterValue': u'admin',
                          'ParameterKey': u'DBRootPassword'},
                         {'ParameterValue': u'admin',
                          'ParameterKey': u'DBPassword'},
                         {'ParameterValue': u'wordpress',
                          'ParameterKey': u'DBName'}],
                        'Outputs':
                        [{'OutputKey': u'WebsiteURL',
                          'OutputValue': u'http://10.0.0.8/wordpress',
                          'Description': u'URL for Wordpress wiki'}],
                        'TimeoutInMinutes': 60,
                        'CreationTime': u'2012-07-09T09:12:45Z',
                        'Capabilities': [],
                        'StackName': u'wordpress',
                        'NotificationARNs': [],
                        'StackStatus': u'CREATE_COMPLETE',
                        'DisableRollback': 'true',
                        'LastUpdatedTime': u'2012-07-09T09:13:11Z'}]}}}

        self.assertEqual(expected, response)

    def test_describe_arn(self):
        # Format a dummy GET request to pass into the WSGI handler
        stack_name = u"wordpress"
        stack_identifier = identifier.HeatIdentifier('t', stack_name, '6')
        identity = dict(stack_identifier)
        params = {'Action': 'DescribeStacks',
                  'StackName': stack_identifier.arn()}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStacks')

        # Stub out the RPC call to the engine with a pre-canned response
        # Note the engine returns a load of keys we don't actually use
        # so this is a subset of the real response format
        engine_resp = [{u'stack_identity': {u'tenant': u't',
                                            u'stack_name': u'wordpress',
                                            u'stack_id': u'6',
                                            u'path': u''},
                        u'updated_time': u'2012-07-09T09:13:11Z',
                        u'parameters': {u'DBUsername': u'admin',
                                        u'LinuxDistribution': u'F17',
                                        u'InstanceType': u'm1.large',
                                        u'DBRootPassword': u'admin',
                                        u'DBPassword': u'admin',
                                        u'DBName': u'wordpress'},
                        u'outputs':
                        [{u'output_key': u'WebsiteURL',
                          u'description': u'URL for Wordpress wiki',
                          u'output_value': u'http://10.0.0.8/wordpress'}],
                        u'stack_status_reason': u'Stack successfully created',
                        u'creation_time': u'2012-07-09T09:12:45Z',
                        u'stack_name': u'wordpress',
                        u'notification_topics': [],
                        u'stack_action': u'CREATE',
                        u'stack_status': u'COMPLETE',
                        u'description': u'blah',
                        u'disable_rollback': 'true',
                        u'timeout_mins':60,
                        u'capabilities':[]}]

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('show_stack', {'stack_identity': identity})
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        # Call the list controller function and compare the response
        response = self.controller.describe(dummy_req)

        expected = {'DescribeStacksResponse':
                    {'DescribeStacksResult':
                     {'Stacks':
                      [{'StackId': u'arn:openstack:heat::t:stacks/wordpress/6',
                        'StackStatusReason': u'Stack successfully created',
                        'Description': u'blah',
                        'Parameters':
                        [{'ParameterValue': u'admin',
                          'ParameterKey': u'DBUsername'},
                         {'ParameterValue': u'F17',
                          'ParameterKey': u'LinuxDistribution'},
                         {'ParameterValue': u'm1.large',
                          'ParameterKey': u'InstanceType'},
                         {'ParameterValue': u'admin',
                          'ParameterKey': u'DBRootPassword'},
                         {'ParameterValue': u'admin',
                          'ParameterKey': u'DBPassword'},
                         {'ParameterValue': u'wordpress',
                          'ParameterKey': u'DBName'}],
                        'Outputs':
                        [{'OutputKey': u'WebsiteURL',
                          'OutputValue': u'http://10.0.0.8/wordpress',
                          'Description': u'URL for Wordpress wiki'}],
                        'TimeoutInMinutes': 60,
                        'CreationTime': u'2012-07-09T09:12:45Z',
                        'Capabilities': [],
                        'StackName': u'wordpress',
                        'NotificationARNs': [],
                        'StackStatus': u'CREATE_COMPLETE',
                        'DisableRollback': 'true',
                        'LastUpdatedTime': u'2012-07-09T09:13:11Z'}]}}}

        self.assertEqual(expected, response)

    def test_describe_arn_invalidtenant(self):
        # Format a dummy GET request to pass into the WSGI handler
        stack_name = u"wordpress"
        stack_identifier = identifier.HeatIdentifier('wibble', stack_name, '6')
        identity = dict(stack_identifier)
        params = {'Action': 'DescribeStacks',
                  'StackName': stack_identifier.arn()}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStacks')

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('show_stack', {'stack_identity': identity})
        ).AndRaise(heat_exception.InvalidTenant(target='test',
                                                actual='test'))

        self.m.ReplayAll()

        result = self.controller.describe(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_describe_aterr(self):
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStacks', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStacks')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context, ('show_stack', {'stack_identity': identity})
        ).AndRaise(AttributeError())

        self.m.ReplayAll()

        result = self.controller.describe(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_describe_bad_name(self):
        stack_name = "wibble"
        params = {'Action': 'DescribeStacks', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStacks')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.describe(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_get_template_int_body(self):
        '''Test the internal _get_template function.'''
        params = {'TemplateBody': "abcdef"}
        dummy_req = self._dummy_GET_request(params)
        result = self.controller._get_template(dummy_req)
        expected = "abcdef"
        self.assertEqual(expected, result)

    # TODO(shardy) : test the _get_template TemplateUrl case

    def _stub_rpc_create_stack_call_failure(self, req_context, stack_name,
                                            engine_parms, engine_args,
                                            failure, need_stub=True):
        if need_stub:
            self.m.StubOutWithMock(policy.Enforcer, 'enforce')
            self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        policy.Enforcer.enforce(req_context,
                                'CreateStack').AndReturn(True)

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        rpc_client.EngineClient.call(
            req_context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': self.template,
              'params': engine_parms,
              'files': {},
              'args': engine_args,
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndRaise(failure)

    def _stub_rpc_create_stack_call_success(self, stack_name, engine_parms,
                                            engine_args, parameters):
        dummy_req = self._dummy_GET_request(parameters)
        self._stub_enforce(dummy_req, 'CreateStack')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = {u'tenant': u't',
                       u'stack_name': u'wordpress',
                       u'stack_id': u'1',
                       u'path': u''}

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('create_stack',
             {'stack_name': stack_name,
              'template': self.template,
              'params': engine_parms,
              'files': {},
              'args': engine_args,
              'owner_id': None,
              'nested_depth': 0,
              'user_creds_id': None,
              'stack_user_project_id': None}),
            version='1.2'
        ).AndReturn(engine_resp)

        self.m.ReplayAll()
        return dummy_req

    def test_create(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'DisableRollback': 'true',
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30', 'disable_rollback': 'true'}
        dummy_req = self._stub_rpc_create_stack_call_success(stack_name,
                                                             engine_parms,
                                                             engine_args,
                                                             params)
        response = self.controller.create(dummy_req)

        expected = {
            'CreateStackResponse': {
                'CreateStackResult': {
                    u'StackId': u'arn:openstack:heat::t:stacks/wordpress/1'
                }
            }
        }

        self.assertEqual(expected, response)

    def test_create_rollback(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'DisableRollback': 'false',
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30', 'disable_rollback': 'false'}
        dummy_req = self._stub_rpc_create_stack_call_success(stack_name,
                                                             engine_parms,
                                                             engine_args,
                                                             params)

        response = self.controller.create(dummy_req)

        expected = {
            'CreateStackResponse': {
                'CreateStackResult': {
                    u'StackId': u'arn:openstack:heat::t:stacks/wordpress/1'
                }
            }
        }

        self.assertEqual(expected, response)

    def test_create_onfailure_true(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'OnFailure': 'DO_NOTHING',
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30', 'disable_rollback': 'true'}
        dummy_req = self._stub_rpc_create_stack_call_success(stack_name,
                                                             engine_parms,
                                                             engine_args,
                                                             params)

        response = self.controller.create(dummy_req)

        expected = {
            'CreateStackResponse': {
                'CreateStackResult': {
                    u'StackId': u'arn:openstack:heat::t:stacks/wordpress/1'
                }
            }
        }

        self.assertEqual(expected, response)

    def test_create_onfailure_false_delete(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'OnFailure': 'DELETE',
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30', 'disable_rollback': 'false'}
        dummy_req = self._stub_rpc_create_stack_call_success(stack_name,
                                                             engine_parms,
                                                             engine_args,
                                                             params)

        response = self.controller.create(dummy_req)

        expected = {
            'CreateStackResponse': {
                'CreateStackResult': {
                    u'StackId': u'arn:openstack:heat::t:stacks/wordpress/1'
                }
            }
        }

        self.assertEqual(expected, response)

    def test_create_onfailure_false_rollback(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'OnFailure': 'ROLLBACK',
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30', 'disable_rollback': 'false'}
        dummy_req = self._stub_rpc_create_stack_call_success(stack_name,
                                                             engine_parms,
                                                             engine_args,
                                                             params)

        response = self.controller.create(dummy_req)

        expected = {
            'CreateStackResponse': {
                'CreateStackResult': {
                    u'StackId': u'arn:openstack:heat::t:stacks/wordpress/1'
                }
            }
        }

        self.assertEqual(expected, response)

    def test_create_onfailure_err(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'DisableRollback': 'true',
                  'OnFailure': 'DO_NOTHING',
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'CreateStack')

        self.assertRaises(exception.HeatInvalidParameterCombinationError,
                          self.controller.create, dummy_req)

    def test_create_err_no_template(self):
        # Format a dummy request with a missing template field
        stack_name = "wordpress"
        params = {'Action': 'CreateStack', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'CreateStack')

        result = self.controller.create(dummy_req)
        self.assertIsInstance(result, exception.HeatMissingParameterError)

    def test_create_err_inval_template(self):
        # Format a dummy request with an invalid TemplateBody
        stack_name = "wordpress"
        json_template = "!$%**_+}@~?"
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'CreateStack')

        result = self.controller.create(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_create_err_rpcerr(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_rpc_create_stack_call_failure(dummy_req.context,
                                                 stack_name,
                                                 engine_parms,
                                                 engine_args,
                                                 AttributeError())
        failure = heat_exception.UnknownUserParameter(key='test')
        self._stub_rpc_create_stack_call_failure(dummy_req.context,
                                                 stack_name,
                                                 engine_parms,
                                                 engine_args,
                                                 failure,
                                                 False)
        failure = heat_exception.UserParameterMissing(key='test')
        self._stub_rpc_create_stack_call_failure(dummy_req.context,
                                                 stack_name,
                                                 engine_parms,
                                                 engine_args,
                                                 failure,
                                                 False)
        self.m.ReplayAll()

        result = self.controller.create(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

        result = self.controller.create(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

        result = self.controller.create(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_create_err_exists(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30'}
        failure = heat_exception.StackExists(stack_name='test')
        dummy_req = self._dummy_GET_request(params)
        self._stub_rpc_create_stack_call_failure(dummy_req.context,
                                                 stack_name,
                                                 engine_parms,
                                                 engine_args,
                                                 failure)

        self.m.ReplayAll()
        result = self.controller.create(dummy_req)

        self.assertIsInstance(result, exception.AlreadyExistsError)

    def test_create_err_engine(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'CreateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'TimeoutInMinutes': 30,
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {'timeout_mins': u'30'}
        failure = heat_exception.StackValidationFailed(
            message='Something went wrong')
        dummy_req = self._dummy_GET_request(params)
        self._stub_rpc_create_stack_call_failure(dummy_req.context,
                                                 stack_name,
                                                 engine_parms,
                                                 engine_args,
                                                 failure)
        self.m.ReplayAll()
        result = self.controller.create(dummy_req)

        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_update(self):
        # Format a dummy request
        stack_name = "wordpress"
        json_template = json.dumps(self.template)
        params = {'Action': 'UpdateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        engine_parms = {u'InstanceType': u'm1.xlarge'}
        engine_args = {}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'UpdateStack')

        # Stub out the RPC call to the engine with a pre-canned response
        identity = dict(identifier.HeatIdentifier('t', stack_name, '1'))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)

        rpc_client.EngineClient.call(
            dummy_req.context,
            ('update_stack',
             {'stack_identity': identity,
              'template': self.template,
              'params': engine_parms,
              'files': {},
              'args': engine_args})
        ).AndReturn(identity)

        self.m.ReplayAll()

        response = self.controller.update(dummy_req)

        expected = {
            'UpdateStackResponse': {
                'UpdateStackResult': {
                    u'StackId': u'arn:openstack:heat::t:stacks/wordpress/1'
                }
            }
        }

        self.assertEqual(expected, response)

    def test_cancel_update(self):
        # Format a dummy request
        stack_name = "wordpress"
        params = {'Action': 'CancelUpdateStack', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'CancelUpdateStack')

        # Stub out the RPC call to the engine with a pre-canned response
        identity = dict(identifier.HeatIdentifier('t', stack_name, '1'))

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)

        rpc_client.EngineClient.call(
            dummy_req.context,
            ('stack_cancel_update',
             {'stack_identity': identity})
        ).AndReturn(identity)

        self.m.ReplayAll()

        response = self.controller.cancel_update(dummy_req)

        expected = {
            'CancelUpdateStackResponse': {
                'CancelUpdateStackResult': {}
            }
        }

        self.assertEqual(response, expected)

    def test_update_bad_name(self):
        stack_name = "wibble"
        json_template = json.dumps(self.template)
        params = {'Action': 'UpdateStack', 'StackName': stack_name,
                  'TemplateBody': '%s' % json_template,
                  'Parameters.member.1.ParameterKey': 'InstanceType',
                  'Parameters.member.1.ParameterValue': 'm1.xlarge'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'UpdateStack')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.update(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_create_or_update_err(self):
        result = self.controller.create_or_update(req={}, action="dsdgfdf")
        self.assertIsInstance(result, exception.HeatInternalFailureError)

    def test_get_template(self):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'GetTemplate', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'GetTemplate')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = self.template

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('get_template', {'stack_identity': identity})
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.get_template(dummy_req)

        expected = {'GetTemplateResponse':
                    {'GetTemplateResult':
                     {'TemplateBody': self.template}}}

        self.assertEqual(expected, response)

    def test_get_template_err_rpcerr(self):
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'GetTemplate', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'GetTemplate')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context, ('get_template', {'stack_identity': identity})
        ).AndRaise(AttributeError())

        self.m.ReplayAll()

        result = self.controller.get_template(dummy_req)

        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_get_template_bad_name(self):
        stack_name = "wibble"
        params = {'Action': 'GetTemplate', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'GetTemplate')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.get_template(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_get_template_err_none(self):
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'GetTemplate', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'GetTemplate')

        # Stub out the RPC call to the engine to return None
        # this test the "no such stack" error path
        engine_resp = None

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context, ('get_template', {'stack_identity': identity})
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        result = self.controller.get_template(dummy_req)

        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_validate_err_no_template(self):
        # Format a dummy request with a missing template field
        params = {'Action': 'ValidateTemplate'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ValidateTemplate')

        result = self.controller.validate_template(dummy_req)
        self.assertIsInstance(result, exception.HeatMissingParameterError)

    def test_validate_err_inval_template(self):
        # Format a dummy request with an invalid TemplateBody
        json_template = "!$%**_+}@~?"
        params = {'Action': 'ValidateTemplate',
                  'TemplateBody': '%s' % json_template}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ValidateTemplate')

        result = self.controller.validate_template(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_bad_resources_in_template(self):
        # Format a dummy request
        json_template = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Resources': {
                'Type': 'AWS: : EC2: : Instance',
            },
        }
        params = {'Action': 'ValidateTemplate',
                  'TemplateBody': '%s' % json.dumps(json_template)}
        response = {'Error': 'Resources must contain Resource. '
                    'Found a [string] instead'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ValidateTemplate')

        # Stub out the RPC call to the engine with a pre-canned response
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('validate_template', {'template': json_template, 'params': None})
        ).AndReturn(response)
        self.m.ReplayAll()

        response = self.controller.validate_template(dummy_req)

        expected = {'ValidateTemplateResponse':
                    {'ValidateTemplateResult':
                     'Resources must contain Resource. '
                     'Found a [string] instead'}}
        self.assertEqual(expected, response)

    def test_delete(self):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '1'))
        params = {'Action': 'DeleteStack', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DeleteStack')

        # Stub out the RPC call to the engine with a pre-canned response
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        # Engine returns None when delete successful
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('delete_stack', {'stack_identity': identity})
        ).AndReturn(None)

        self.m.ReplayAll()

        response = self.controller.delete(dummy_req)

        expected = {'DeleteStackResponse': {'DeleteStackResult': ''}}

        self.assertEqual(expected, response)

    def test_delete_err_rpcerr(self):
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '1'))
        params = {'Action': 'DeleteStack', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DeleteStack')

        # Stub out the RPC call to the engine with a pre-canned response
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        rpc_client.EngineClient.call(
            dummy_req.context, ('delete_stack', {'stack_identity': identity})
        ).AndRaise(AttributeError())

        self.m.ReplayAll()

        result = self.controller.delete(dummy_req)

        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_delete_bad_name(self):
        stack_name = "wibble"
        params = {'Action': 'DeleteStack', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DeleteStack')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.delete(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_events_list_event_id_integer(self):
        self._test_events_list('42')

    def test_events_list_event_id_uuid(self):
        self._test_events_list('a3455d8c-9f88-404d-a85b-5315293e67de')

    def _test_events_list(self, event_id):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStackEvents', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackEvents')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = [{u'stack_name': u'wordpress',
                        u'event_time': u'2012-07-23T13:05:39Z',
                        u'stack_identity': {u'tenant': u't',
                                            u'stack_name': u'wordpress',
                                            u'stack_id': u'6',
                                            u'path': u''},
                        u'resource_name': u'WikiDatabase',
                        u'resource_status_reason': u'state changed',
                        u'event_identity':
                        {u'tenant': u't',
                         u'stack_name': u'wordpress',
                         u'stack_id': u'6',
                         u'path': u'/resources/WikiDatabase/events/{0}'.format(
                             event_id)},
                        u'resource_action': u'TEST',
                        u'resource_status': u'IN_PROGRESS',
                        u'physical_resource_id': None,
                        u'resource_properties': {u'UserData': u'blah'},
                        u'resource_type': u'AWS::EC2::Instance'}]

        kwargs = {'stack_identity': identity,
                  'limit': None, 'sort_keys': None, 'marker': None,
                  'sort_dir': None, 'filters': None}
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context, ('list_events', kwargs)
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.events_list(dummy_req)

        expected = {'DescribeStackEventsResponse':
                    {'DescribeStackEventsResult':
                     {'StackEvents':
                      [{'EventId': six.text_type(event_id),
                        'StackId': u'arn:openstack:heat::t:stacks/wordpress/6',
                        'ResourceStatus': u'TEST_IN_PROGRESS',
                        'ResourceType': u'AWS::EC2::Instance',
                        'Timestamp': u'2012-07-23T13:05:39Z',
                        'StackName': u'wordpress',
                        'ResourceProperties':
                        json.dumps({u'UserData': u'blah'}),
                        'PhysicalResourceId': None,
                        'ResourceStatusReason': u'state changed',
                        'LogicalResourceId': u'WikiDatabase'}]}}}

        self.assertEqual(expected, response)

    def test_events_list_err_rpcerr(self):
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStackEvents', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackEvents')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context, ('list_events', {'stack_identity': identity})
        ).AndRaise(Exception())

        self.m.ReplayAll()

        result = self.controller.events_list(dummy_req)

        self.assertIsInstance(result, exception.HeatInternalFailureError)

    def test_events_list_bad_name(self):
        stack_name = "wibble"
        params = {'Action': 'DescribeStackEvents', 'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackEvents')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.events_list(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_describe_stack_resource(self):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStackResource',
                  'StackName': stack_name,
                  'LogicalResourceId': "WikiDatabase"}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResource')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = {u'description': u'',
                       u'resource_identity': {
                           u'tenant': u't',
                           u'stack_name': u'wordpress',
                           u'stack_id': u'6',
                           u'path': u'resources/WikiDatabase'
                       },
                       u'stack_name': u'wordpress',
                       u'resource_name': u'WikiDatabase',
                       u'resource_status_reason': None,
                       u'updated_time': u'2012-07-23T13:06:00Z',
                       u'stack_identity': {u'tenant': u't',
                                           u'stack_name': u'wordpress',
                                           u'stack_id': u'6',
                                           u'path': u''},
                       u'resource_action': u'CREATE',
                       u'resource_status': u'COMPLETE',
                       u'physical_resource_id':
                       u'a3455d8c-9f88-404d-a85b-5315293e67de',
                       u'resource_type': u'AWS::EC2::Instance',
                       u'metadata': {u'wordpress': []}}

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        args = {
            'stack_identity': identity,
            'resource_name': dummy_req.params.get('LogicalResourceId'),
            'with_attr': None,
        }
        rpc_client.EngineClient.call(
            dummy_req.context, ('describe_stack_resource', args), version='1.2'
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.describe_stack_resource(dummy_req)

        expected = {'DescribeStackResourceResponse':
                    {'DescribeStackResourceResult':
                     {'StackResourceDetail':
                      {'StackId': u'arn:openstack:heat::t:stacks/wordpress/6',
                       'ResourceStatus': u'CREATE_COMPLETE',
                       'Description': u'',
                       'ResourceType': u'AWS::EC2::Instance',
                       'ResourceStatusReason': None,
                       'LastUpdatedTimestamp': u'2012-07-23T13:06:00Z',
                       'StackName': u'wordpress',
                       'PhysicalResourceId':
                       u'a3455d8c-9f88-404d-a85b-5315293e67de',
                       'Metadata': {u'wordpress': []},
                       'LogicalResourceId': u'WikiDatabase'}}}}

        self.assertEqual(expected, response)

    def test_describe_stack_resource_nonexistent_stack(self):
        # Format a dummy request
        stack_name = "wibble"
        params = {'Action': 'DescribeStackResource',
                  'StackName': stack_name,
                  'LogicalResourceId': "WikiDatabase"}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResource')

        # Stub out the RPC call to the engine with a pre-canned response
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.describe_stack_resource(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_describe_stack_resource_nonexistent(self):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStackResource',
                  'StackName': stack_name,
                  'LogicalResourceId': "wibble"}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResource')

        # Stub out the RPC call to the engine with a pre-canned response
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        args = {
            'stack_identity': identity,
            'resource_name': dummy_req.params.get('LogicalResourceId'),
            'with_attr': None,
        }
        rpc_client.EngineClient.call(
            dummy_req.context, ('describe_stack_resource', args), version='1.2'
        ).AndRaise(heat_exception.ResourceNotFound(
            resource_name='test', stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.describe_stack_resource(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_describe_stack_resources(self):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStackResources',
                  'StackName': stack_name,
                  'LogicalResourceId': "WikiDatabase"}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResources')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = [{u'description': u'',
                        u'resource_identity': {
                            u'tenant': u't',
                            u'stack_name': u'wordpress',
                            u'stack_id': u'6',
                            u'path': u'resources/WikiDatabase'
                        },
                        u'stack_name': u'wordpress',
                        u'resource_name': u'WikiDatabase',
                        u'resource_status_reason': None,
                        u'updated_time': u'2012-07-23T13:06:00Z',
                        u'stack_identity': {u'tenant': u't',
                                            u'stack_name': u'wordpress',
                                            u'stack_id': u'6',
                                            u'path': u''},
                        u'resource_action': u'CREATE',
                        u'resource_status': u'COMPLETE',
                        u'physical_resource_id':
                        u'a3455d8c-9f88-404d-a85b-5315293e67de',
                        u'resource_type': u'AWS::EC2::Instance',
                        u'metadata': {u'ensureRunning': u'true''true'}}]

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        args = {
            'stack_identity': identity,
            'resource_name': dummy_req.params.get('LogicalResourceId'),
        }
        rpc_client.EngineClient.call(
            dummy_req.context, ('describe_stack_resources', args)
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.describe_stack_resources(dummy_req)

        expected = {'DescribeStackResourcesResponse':
                    {'DescribeStackResourcesResult':
                     {'StackResources':
                      [{'StackId': u'arn:openstack:heat::t:stacks/wordpress/6',
                        'ResourceStatus': u'CREATE_COMPLETE',
                        'Description': u'',
                        'ResourceType': u'AWS::EC2::Instance',
                        'Timestamp': u'2012-07-23T13:06:00Z',
                        'ResourceStatusReason': None,
                        'StackName': u'wordpress',
                        'PhysicalResourceId':
                        u'a3455d8c-9f88-404d-a85b-5315293e67de',
                        'LogicalResourceId': u'WikiDatabase'}]}}}

        self.assertEqual(expected, response)

    def test_describe_stack_resources_bad_name(self):
        stack_name = "wibble"
        params = {'Action': 'DescribeStackResources',
                  'StackName': stack_name,
                  'LogicalResourceId': "WikiDatabase"}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResources')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.describe_stack_resources(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)

    def test_describe_stack_resources_physical(self):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'DescribeStackResources',
                  'LogicalResourceId': "WikiDatabase",
                  'PhysicalResourceId': 'a3455d8c-9f88-404d-a85b-5315293e67de'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResources')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = [{u'description': u'',
                        u'resource_identity': {
                            u'tenant': u't',
                            u'stack_name': u'wordpress',
                            u'stack_id': u'6',
                            u'path': u'resources/WikiDatabase'
                        },
                        u'stack_name': u'wordpress',
                        u'resource_name': u'WikiDatabase',
                        u'resource_status_reason': None,
                        u'updated_time': u'2012-07-23T13:06:00Z',
                        u'stack_identity': {u'tenant': u't',
                                            u'stack_name': u'wordpress',
                                            u'stack_id': u'6',
                                            u'path': u''},
                        u'resource_action': u'CREATE',
                        u'resource_status': u'COMPLETE',
                        u'physical_resource_id':
                        u'a3455d8c-9f88-404d-a85b-5315293e67de',
                        u'resource_type': u'AWS::EC2::Instance',
                        u'metadata': {u'ensureRunning': u'true''true'}}]

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('find_physical_resource',
             {'physical_resource_id': 'a3455d8c-9f88-404d-a85b-5315293e67de'})
        ).AndReturn(identity)
        args = {
            'stack_identity': identity,
            'resource_name': dummy_req.params.get('LogicalResourceId'),
        }
        rpc_client.EngineClient.call(
            dummy_req.context, ('describe_stack_resources', args)
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.describe_stack_resources(dummy_req)

        expected = {'DescribeStackResourcesResponse':
                    {'DescribeStackResourcesResult':
                     {'StackResources':
                      [{'StackId': u'arn:openstack:heat::t:stacks/wordpress/6',
                        'ResourceStatus': u'CREATE_COMPLETE',
                        'Description': u'',
                        'ResourceType': u'AWS::EC2::Instance',
                        'Timestamp': u'2012-07-23T13:06:00Z',
                        'ResourceStatusReason': None,
                        'StackName': u'wordpress',
                        'PhysicalResourceId':
                        u'a3455d8c-9f88-404d-a85b-5315293e67de',
                        'LogicalResourceId': u'WikiDatabase'}]}}}

        self.assertEqual(expected, response)

    def test_describe_stack_resources_physical_not_found(self):
        # Format a dummy request
        params = {'Action': 'DescribeStackResources',
                  'LogicalResourceId': "WikiDatabase",
                  'PhysicalResourceId': 'aaaaaaaa-9f88-404d-cccc-ffffffffffff'}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResources')

        # Stub out the RPC call to the engine with a pre-canned response
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('find_physical_resource',
             {'physical_resource_id': 'aaaaaaaa-9f88-404d-cccc-ffffffffffff'})
        ).AndRaise(heat_exception.PhysicalResourceNotFound(
            resource_id='1'))

        self.m.ReplayAll()

        response = self.controller.describe_stack_resources(dummy_req)

        self.assertIsInstance(response,
                              exception.HeatInvalidParameterValueError)

    def test_describe_stack_resources_err_inval(self):
        # Format a dummy request containing both StackName and
        # PhysicalResourceId, which is invalid and should throw a
        # HeatInvalidParameterCombinationError
        stack_name = "wordpress"
        params = {'Action': 'DescribeStackResources',
                  'StackName': stack_name,
                  'PhysicalResourceId': "123456"}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'DescribeStackResources')
        ret = self.controller.describe_stack_resources(dummy_req)
        self.assertIsInstance(ret,
                              exception.HeatInvalidParameterCombinationError)

    def test_list_stack_resources(self):
        # Format a dummy request
        stack_name = "wordpress"
        identity = dict(identifier.HeatIdentifier('t', stack_name, '6'))
        params = {'Action': 'ListStackResources',
                  'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ListStackResources')

        # Stub out the RPC call to the engine with a pre-canned response
        engine_resp = [{u'resource_identity':
                        {u'tenant': u't',
                         u'stack_name': u'wordpress',
                         u'stack_id': u'6',
                         u'path': u'/resources/WikiDatabase'},
                        u'stack_name': u'wordpress',
                        u'resource_name': u'WikiDatabase',
                        u'resource_status_reason': None,
                        u'updated_time': u'2012-07-23T13:06:00Z',
                        u'stack_identity': {u'tenant': u't',
                                            u'stack_name': u'wordpress',
                                            u'stack_id': u'6',
                                            u'path': u''},
                        u'resource_action': u'CREATE',
                        u'resource_status': u'COMPLETE',
                        u'physical_resource_id':
                        u'a3455d8c-9f88-404d-a85b-5315293e67de',
                        u'resource_type': u'AWS::EC2::Instance'}]

        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndReturn(identity)
        rpc_client.EngineClient.call(
            dummy_req.context,
            ('list_stack_resources', {'stack_identity': identity,
                                      'nested_depth': 0})
        ).AndReturn(engine_resp)

        self.m.ReplayAll()

        response = self.controller.list_stack_resources(dummy_req)

        expected = {'ListStackResourcesResponse': {'ListStackResourcesResult':
                    {'StackResourceSummaries':
                     [{'ResourceStatus': u'CREATE_COMPLETE',
                       'ResourceType': u'AWS::EC2::Instance',
                       'ResourceStatusReason': None,
                       'LastUpdatedTimestamp': u'2012-07-23T13:06:00Z',
                       'PhysicalResourceId':
                       u'a3455d8c-9f88-404d-a85b-5315293e67de',
                       'LogicalResourceId': u'WikiDatabase'}]}}}

        self.assertEqual(expected, response)

    def test_list_stack_resources_bad_name(self):
        stack_name = "wibble"
        params = {'Action': 'ListStackResources',
                  'StackName': stack_name}
        dummy_req = self._dummy_GET_request(params)
        self._stub_enforce(dummy_req, 'ListStackResources')

        # Insert an engine RPC error and ensure we map correctly to the
        # heat exception type
        self.m.StubOutWithMock(rpc_client.EngineClient, 'call')
        rpc_client.EngineClient.call(
            dummy_req.context, ('identify_stack', {'stack_name': stack_name})
        ).AndRaise(heat_exception.StackNotFound(stack_name='test'))

        self.m.ReplayAll()

        result = self.controller.list_stack_resources(dummy_req)
        self.assertIsInstance(result, exception.HeatInvalidParameterValueError)
