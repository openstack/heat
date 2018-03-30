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

import datetime
import uuid

import mock
from oslo_messaging.rpc import dispatcher
from oslo_serialization import jsonutils as json
from oslo_utils import timeutils
import six

from heat.common import crypt
from heat.common import exception
from heat.common import template_format
from heat.db.sqlalchemy import api as db_api
from heat.engine.clients.os import swift
from heat.engine.clients.os import zaqar
from heat.engine import service
from heat.engine import service_software_config
from heat.engine import software_config_io as swc_io
from heat.objects import resource as resource_objects
from heat.objects import software_config as software_config_object
from heat.objects import software_deployment as software_deployment_object
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import utils

software_config_inputs = '''
heat_template_version: 2013-05-23
description: Validate software config input/output types

resources:

  InputOutputTestConfig:
    type: OS::Heat::SoftwareConfig
    properties:
      group: puppet
      inputs:
      - name: boolean_input
        type: Boolean
      - name: json_input
        type: Json
      - name: number_input
        type: Number
      - name: string_input
        type: String
      - name: comma_delimited_list_input
        type: CommaDelimitedList
      outputs:
      - name: boolean_output
        type: Boolean
      - name: json_output
        type: Json
      - name: number_output
        type: Number
      - name: string_output
        type: String
      - name: comma_delimited_list_output
        type: CommaDelimitedList

'''


class SoftwareConfigServiceTest(common.HeatTestCase):

    def setUp(self):
        super(SoftwareConfigServiceTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.engine = service.EngineService('a-host', 'a-topic')

    def _create_software_config(
            self, group='Heat::Shell', name='config_mysql', config=None,
            inputs=None, outputs=None, options=None, context=None):
        cntx = context if context else self.ctx
        inputs = inputs or []
        outputs = outputs or []
        options = options or {}
        return self.engine.create_software_config(
            cntx, group, name, config, inputs, outputs, options)

    def _create_dummy_config_object(self):
        obj_config = software_config_object.SoftwareConfig()
        obj_config['id'] = str(uuid.uuid4())
        obj_config['name'] = 'myconfig'
        obj_config['group'] = 'mygroup'
        obj_config['config'] = {'config': 'hello world',
                                'inputs': [],
                                'outputs': [],
                                'options': {}}
        obj_config['created_at'] = timeutils.utcnow()
        return obj_config

    def assert_status_reason(self, expected, actual):
        expected_dict = dict((i.split(' : ') for i in expected.split(', ')))
        actual_dict = dict((i.split(' : ') for i in actual.split(', ')))
        self.assertEqual(expected_dict, actual_dict)

    def test_list_software_configs(self):
        config = self._create_software_config()
        self.assertIsNotNone(config)
        config_id = config['id']

        configs = self.engine.list_software_configs(self.ctx)
        self.assertIsNotNone(configs)
        config_ids = [x['id'] for x in configs]
        self.assertIn(config_id, config_ids)

        admin_cntx = utils.dummy_context(is_admin=True)

        admin_config = self._create_software_config(context=admin_cntx)
        admin_config_id = admin_config['id']
        configs = self.engine.list_software_configs(admin_cntx)
        self.assertIsNotNone(configs)
        config_ids = [x['id'] for x in configs]
        project_ids = [x['project'] for x in configs]
        self.assertEqual(2, len(project_ids))
        self.assertEqual(2, len(config_ids))
        self.assertIn(config_id, config_ids)
        self.assertIn(admin_config_id, config_ids)

    def test_show_software_config(self):
        config_id = str(uuid.uuid4())

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_software_config,
                               self.ctx, config_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        config = self._create_software_config()
        res = self.engine.show_software_config(self.ctx, config['id'])
        self.assertEqual(config, res)

    def test_create_software_config_new_ids(self):
        config1 = self._create_software_config()
        self.assertIsNotNone(config1)

        config2 = self._create_software_config()
        self.assertNotEqual(config1['id'], config2['id'])

    def test_create_software_config(self):
        kwargs = {
            'group': 'Heat::Chef',
            'name': 'config_heat',
            'config': '...',
            'inputs': [{'name': 'mode'}],
            'outputs': [{'name': 'endpoint'}],
            'options': {}
        }
        config = self._create_software_config(**kwargs)
        config_id = config['id']
        config = self.engine.show_software_config(self.ctx, config_id)
        self.assertEqual(kwargs['group'], config['group'])
        self.assertEqual(kwargs['name'], config['name'])
        self.assertEqual(kwargs['config'], config['config'])
        self.assertEqual([{'name': 'mode', 'type': 'String'}],
                         config['inputs'])
        self.assertEqual([{'name': 'endpoint', 'type': 'String',
                           'error_output': False}],
                         config['outputs'])
        self.assertEqual(kwargs['options'], config['options'])

    def test_delete_software_config(self):
        config = self._create_software_config()
        self.assertIsNotNone(config)
        config_id = config['id']
        self.engine.delete_software_config(self.ctx, config_id)

        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_software_config,
                               self.ctx, config_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

    def test_boolean_inputs_valid(self):
        stack_name = 'test_boolean_inputs_valid'
        t = template_format.parse(software_config_inputs)
        stack = utils.parse_stack(t, stack_name=stack_name)
        try:
            stack.validate()
        except exception.StackValidationFailed as exc:
            self.fail("Validation should have passed: %s" % six.text_type(exc))

    def _create_software_deployment(self, config_id=None, input_values=None,
                                    action='INIT',
                                    status='COMPLETE', status_reason='',
                                    config_group=None,
                                    server_id=str(uuid.uuid4()),
                                    config_name=None,
                                    stack_user_project_id=None):
        input_values = input_values or {}
        if config_id is None:
            config = self._create_software_config(group=config_group,
                                                  name=config_name)
            config_id = config['id']
        return self.engine.create_software_deployment(
            self.ctx, server_id, config_id, input_values,
            action, status, status_reason, stack_user_project_id)

    def test_list_software_deployments(self):
        stack_name = 'test_list_software_deployments'
        t = template_format.parse(tools.wp_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        fc = tools.setup_mocks_with_mock(self, stack)
        stack.store()
        stack.create()
        server = stack['WebServer']
        server_id = server.resource_id
        deployment = self._create_software_deployment(
            server_id=server_id)
        deployment_id = deployment['id']
        self.assertIsNotNone(deployment)

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=None)
        self.assertIsNotNone(deployments)
        deployment_ids = [x['id'] for x in deployments]
        self.assertIn(deployment_id, deployment_ids)
        self.assertIn(deployment, deployments)

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=str(uuid.uuid4()))
        self.assertEqual([], deployments)

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=server.resource_id)
        self.assertEqual([deployment], deployments)

        rsrcs = resource_objects.Resource.get_all_by_physical_resource_id(
            self.ctx, server_id)
        self.assertEqual(deployment['config_id'],
                         rsrcs[0].rsrc_metadata.get('deployments')[0]['id'])
        tools.validate_setup_mocks_with_mock(stack, fc)

    def test_metadata_software_deployments(self):
        stack_name = 'test_metadata_software_deployments'
        t = template_format.parse(tools.wp_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        fc = tools.setup_mocks_with_mock(self, stack)
        stack.store()
        stack.create()
        server = stack['WebServer']
        server_id = server.resource_id

        stack_user_project_id = str(uuid.uuid4())
        d1 = self._create_software_deployment(
            config_group='mygroup',
            server_id=server_id,
            config_name='02_second',
            stack_user_project_id=stack_user_project_id)
        d2 = self._create_software_deployment(
            config_group='mygroup',
            server_id=server_id,
            config_name='01_first',
            stack_user_project_id=stack_user_project_id)
        d3 = self._create_software_deployment(
            config_group='myothergroup',
            server_id=server_id,
            config_name='03_third',
            stack_user_project_id=stack_user_project_id)
        metadata = self.engine.metadata_software_deployments(
            self.ctx, server_id=server_id)
        self.assertEqual(3, len(metadata))
        self.assertEqual('mygroup', metadata[1]['group'])
        self.assertEqual('mygroup', metadata[0]['group'])
        self.assertEqual('myothergroup', metadata[2]['group'])
        self.assertEqual(d1['config_id'], metadata[1]['id'])
        self.assertEqual(d2['config_id'], metadata[0]['id'])
        self.assertEqual(d3['config_id'], metadata[2]['id'])
        self.assertEqual('01_first', metadata[0]['name'])
        self.assertEqual('02_second', metadata[1]['name'])
        self.assertEqual('03_third', metadata[2]['name'])

        # assert that metadata via metadata_software_deployments matches
        # metadata via server resource
        rsrcs = resource_objects.Resource.get_all_by_physical_resource_id(
            self.ctx, server_id)
        self.assertEqual(metadata, rsrcs[0].rsrc_metadata.get('deployments'))

        deployments = self.engine.metadata_software_deployments(
            self.ctx, server_id=str(uuid.uuid4()))
        self.assertEqual([], deployments)

        # assert get results when the context tenant_id matches
        # the stored stack_user_project_id
        ctx = utils.dummy_context(tenant_id=stack_user_project_id)
        metadata = self.engine.metadata_software_deployments(
            ctx, server_id=server_id)
        self.assertEqual(3, len(metadata))

        # assert get no results when the context tenant_id is unknown
        ctx = utils.dummy_context(tenant_id=str(uuid.uuid4()))
        metadata = self.engine.metadata_software_deployments(
            ctx, server_id=server_id)
        self.assertEqual(0, len(metadata))

        # assert None config is filtered out
        obj_conf = self._create_dummy_config_object()
        side_effect = [obj_conf, obj_conf, None]
        self.patchobject(software_config_object.SoftwareConfig,
                         '_from_db_object', side_effect=side_effect)
        metadata = self.engine.metadata_software_deployments(
            self.ctx, server_id=server_id)
        self.assertEqual(2, len(metadata))
        tools.validate_setup_mocks_with_mock(stack, fc)

    def test_show_software_deployment(self):
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.show_software_deployment,
                               self.ctx, deployment_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        deployment = self._create_software_deployment()
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        self.assertEqual(
            deployment,
            self.engine.show_software_deployment(self.ctx, deployment_id))

    def test_check_software_deployment(self):
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.check_software_deployment,
                               self.ctx, deployment_id, 10)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        deployment = self._create_software_deployment()
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        self.assertEqual(
            deployment,
            self.engine.check_software_deployment(self.ctx, deployment_id, 10))

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       '_push_metadata_software_deployments')
    def test_signal_software_deployment(self, pmsd):
        self.assertRaises(ValueError,
                          self.engine.signal_software_deployment,
                          self.ctx, None, {}, None)
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.signal_software_deployment,
                               self.ctx, deployment_id, {}, None)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        deployment = self._create_software_deployment()
        deployment_id = deployment['id']

        # signal is ignore unless deployment is IN_PROGRESS
        self.assertIsNone(self.engine.signal_software_deployment(
            self.ctx, deployment_id, {}, None))

        # simple signal, no data
        deployment = self._create_software_deployment(action='INIT',
                                                      status='IN_PROGRESS')
        deployment_id = deployment['id']
        res = self.engine.signal_software_deployment(
            self.ctx, deployment_id, {}, None)
        self.assertEqual('deployment %s succeeded' % deployment_id, res)

        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('COMPLETE', sd.status)
        self.assertEqual('Outputs received', sd.status_reason)
        self.assertEqual({
            'deploy_status_code': None,
            'deploy_stderr': None,
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

        # simple signal, some data
        config = self._create_software_config(outputs=[{'name': 'foo'}])
        deployment = self._create_software_deployment(
            config_id=config['id'], action='INIT', status='IN_PROGRESS')
        deployment_id = deployment['id']
        result = self.engine.signal_software_deployment(
            self.ctx,
            deployment_id,
            {'foo': 'bar', 'deploy_status_code': 0},
            None)
        self.assertEqual('deployment %s succeeded' % deployment_id, result)
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('COMPLETE', sd.status)
        self.assertEqual('Outputs received', sd.status_reason)
        self.assertEqual({
            'deploy_status_code': 0,
            'foo': 'bar',
            'deploy_stderr': None,
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

        # failed signal on deploy_status_code
        config = self._create_software_config(outputs=[{'name': 'foo'}])
        deployment = self._create_software_deployment(
            config_id=config['id'], action='INIT', status='IN_PROGRESS')
        deployment_id = deployment['id']
        result = self.engine.signal_software_deployment(
            self.ctx,
            deployment_id,
            {
                'foo': 'bar',
                'deploy_status_code': -1,
                'deploy_stderr': 'Its gone Pete Tong'
            },
            None)
        self.assertEqual('deployment %s failed (-1)' % deployment_id, result)
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('FAILED', sd.status)
        self.assert_status_reason(
            ('deploy_status_code : Deployment exited with non-zero '
             'status code: -1'),
            sd.status_reason)
        self.assertEqual({
            'deploy_status_code': -1,
            'foo': 'bar',
            'deploy_stderr': 'Its gone Pete Tong',
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

        # failed signal on error_output foo
        config = self._create_software_config(outputs=[
            {'name': 'foo', 'error_output': True}])
        deployment = self._create_software_deployment(
            config_id=config['id'], action='INIT', status='IN_PROGRESS')
        deployment_id = deployment['id']
        result = self.engine.signal_software_deployment(
            self.ctx,
            deployment_id,
            {
                'foo': 'bar',
                'deploy_status_code': -1,
                'deploy_stderr': 'Its gone Pete Tong'
            },
            None)
        self.assertEqual('deployment %s failed' % deployment_id, result)

        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual('FAILED', sd.status)
        self.assert_status_reason(
            ('foo : bar, deploy_status_code : Deployment exited with '
             'non-zero status code: -1'),
            sd.status_reason)
        self.assertEqual({
            'deploy_status_code': -1,
            'foo': 'bar',
            'deploy_stderr': 'Its gone Pete Tong',
            'deploy_stdout': None
        }, sd.output_values)
        self.assertIsNotNone(sd.updated_at)

    def test_create_software_deployment(self):
        kwargs = {
            'group': 'Heat::Chef',
            'name': 'config_heat',
            'config': '...',
            'inputs': [{'name': 'mode'}],
            'outputs': [{'name': 'endpoint'}],
            'options': {}
        }
        config = self._create_software_config(**kwargs)
        config_id = config['id']
        kwargs = {
            'config_id': config_id,
            'input_values': {'mode': 'standalone'},
            'action': 'INIT',
            'status': 'COMPLETE',
            'status_reason': ''
        }
        deployment = self._create_software_deployment(**kwargs)
        deployment_id = deployment['id']
        deployment = self.engine.show_software_deployment(
            self.ctx, deployment_id)
        self.assertEqual(deployment_id, deployment['id'])
        self.assertEqual(kwargs['input_values'], deployment['input_values'])

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       '_refresh_swift_software_deployment')
    def test_show_software_deployment_refresh(
            self, _refresh_swift_software_deployment):
        temp_url = ('http://192.0.2.1/v1/AUTH_a/b/c'
                    '?temp_url_sig=ctemp_url_expires=1234')
        config = self._create_software_config(inputs=[
            {
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'TEMP_URL_SIGNAL'
            }, {
                'name': 'deploy_signal_id',
                'type': 'String',
                'value': temp_url
            }
        ])

        deployment = self._create_software_deployment(
            status='IN_PROGRESS', config_id=config['id'])

        deployment_id = deployment['id']
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        _refresh_swift_software_deployment.return_value = sd
        self.assertEqual(
            deployment,
            self.engine.show_software_deployment(self.ctx, deployment_id))
        self.assertEqual(
            (self.ctx, sd, temp_url),
            _refresh_swift_software_deployment.call_args[0])

    def test_update_software_deployment_new_config(self):

        server_id = str(uuid.uuid4())
        mock_push = self.patchobject(self.engine.software_config,
                                     '_push_metadata_software_deployments')

        deployment = self._create_software_deployment(server_id=server_id)
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        deployment_action = deployment['action']
        self.assertEqual('INIT', deployment_action)
        config_id = deployment['config_id']
        self.assertIsNotNone(config_id)
        updated = self.engine.update_software_deployment(
            self.ctx, deployment_id=deployment_id, config_id=config_id,
            input_values={}, output_values={}, action='DEPLOY',
            status='WAITING', status_reason='', updated_at=None)
        self.assertIsNotNone(updated)
        self.assertEqual(config_id, updated['config_id'])
        self.assertEqual('DEPLOY', updated['action'])
        self.assertEqual('WAITING', updated['status'])
        self.assertEqual(2, mock_push.call_count)

    def test_update_software_deployment_status(self):

        server_id = str(uuid.uuid4())
        mock_push = self.patchobject(self.engine.software_config,
                                     '_push_metadata_software_deployments')

        deployment = self._create_software_deployment(server_id=server_id)

        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']
        deployment_action = deployment['action']
        self.assertEqual('INIT', deployment_action)
        updated = self.engine.update_software_deployment(
            self.ctx, deployment_id=deployment_id, config_id=None,
            input_values=None, output_values={}, action='DEPLOY',
            status='WAITING', status_reason='', updated_at=None)
        self.assertIsNotNone(updated)
        self.assertEqual('DEPLOY', updated['action'])
        self.assertEqual('WAITING', updated['status'])

        mock_push.assert_called_once_with(self.ctx, server_id, None)

    def test_update_software_deployment_fields(self):

        deployment = self._create_software_deployment()
        deployment_id = deployment['id']
        config_id = deployment['config_id']

        def check_software_deployment_updated(**kwargs):
            values = {
                'config_id': None,
                'input_values': {},
                'output_values': {},
                'action': {},
                'status': 'WAITING',
                'status_reason': ''
            }
            values.update(kwargs)
            updated = self.engine.update_software_deployment(
                self.ctx, deployment_id, updated_at=None, **values)
            for key, value in six.iteritems(kwargs):
                self.assertEqual(value, updated[key])

        check_software_deployment_updated(config_id=config_id)
        check_software_deployment_updated(input_values={'foo': 'fooooo'})
        check_software_deployment_updated(output_values={'bar': 'baaaaa'})
        check_software_deployment_updated(action='DEPLOY')
        check_software_deployment_updated(status='COMPLETE')
        check_software_deployment_updated(status_reason='Done!')

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       '_push_metadata_software_deployments')
    def test_delete_software_deployment(self, pmsd):
        deployment_id = str(uuid.uuid4())
        ex = self.assertRaises(dispatcher.ExpectedException,
                               self.engine.delete_software_deployment,
                               self.ctx, deployment_id)
        self.assertEqual(exception.NotFound, ex.exc_info[0])

        deployment = self._create_software_deployment()
        self.assertIsNotNone(deployment)
        deployment_id = deployment['id']

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=None)
        deployment_ids = [x['id'] for x in deployments]
        self.assertIn(deployment_id, deployment_ids)
        self.engine.delete_software_deployment(self.ctx, deployment_id)

        # assert one call for the create, and one for the delete
        pmsd.assert_has_calls([
            mock.call(self.ctx, deployment['server_id'], None),
            mock.call(self.ctx, deployment['server_id'], None)
        ])

        deployments = self.engine.list_software_deployments(
            self.ctx, server_id=None)
        deployment_ids = [x['id'] for x in deployments]
        self.assertNotIn(deployment_id, deployment_ids)

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(service_software_config.requests, 'put')
    def test_push_metadata_software_deployments(
            self, put, res_get, res_upd, md_sd):
        rs = mock.Mock()
        rs.rsrc_metadata = {'original': 'metadata'}
        rs.id = '1234'
        rs.atomic_key = 1
        rs.data = []
        res_get.return_value = rs
        res_upd.return_value = 1

        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments

        result_metadata = {
            'original': 'metadata',
            'deployments': {'deploy': 'this'}
        }

        with mock.patch.object(self.ctx.session, 'refresh'):
            self.engine.software_config._push_metadata_software_deployments(
                self.ctx, '1234', None)
        res_upd.assert_called_once_with(
            self.ctx, '1234', {'rsrc_metadata': result_metadata}, 1)
        put.side_effect = Exception('Unexpected requests.put')

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(service_software_config.requests, 'put')
    def test_push_metadata_software_deployments_retry(
            self, put, res_get, res_upd, md_sd):
        rs = mock.Mock()
        rs.rsrc_metadata = {'original': 'metadata'}
        rs.id = '1234'
        rs.atomic_key = 1
        rs.data = []
        res_get.return_value = rs
        # zero update means another transaction updated
        res_upd.return_value = 0

        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments

        with mock.patch.object(self.ctx.session, 'refresh'):
            f = self.engine.software_config._push_metadata_software_deployments
            self.patchobject(f.retry, 'sleep')
            self.assertRaises(
                exception.ConcurrentTransaction,
                f,
                self.ctx,
                '1234',
                None)
        # retry ten times then the final failure
        self.assertEqual(11, res_upd.call_count)
        put.assert_not_called()

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(service_software_config.requests, 'put')
    def test_push_metadata_software_deployments_temp_url(
            self, put, res_get, res_upd, md_sd):
        rs = mock.Mock()
        rs.rsrc_metadata = {'original': 'metadata'}
        rs.id = '1234'
        rs.atomic_key = 1
        rd = mock.Mock()
        rd.key = 'metadata_put_url'
        rd.value = 'http://192.168.2.2/foo/bar'
        rs.data = [rd]
        res_get.return_value = rs
        res_upd.return_value = 1

        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments

        result_metadata = {
            'original': 'metadata',
            'deployments': {'deploy': 'this'}
        }
        with mock.patch.object(self.ctx.session, 'refresh'):
            self.engine.software_config._push_metadata_software_deployments(
                self.ctx, '1234', None)
        res_upd.has_calls(
            mock.call(self.ctx, '1234',
                      {'rsrc_metadata': result_metadata}, 1),
            mock.call(self.ctx, '1234',
                      {'rsrc_metadata': result_metadata}, 2),
        )

        put.assert_called_once_with(
            'http://192.168.2.2/foo/bar', json.dumps(result_metadata))

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(zaqar.ZaqarClientPlugin, 'create_for_tenant')
    def test_push_metadata_software_deployments_queue(
            self, plugin, res_get, res_upd, md_sd):
        rs = mock.Mock()
        rs.rsrc_metadata = {'original': 'metadata'}
        rs.id = '1234'
        rs.atomic_key = 1
        rd = mock.Mock()
        rd.key = 'metadata_queue_id'
        rd.value = '6789'
        rs.data = [rd]
        res_get.return_value = rs
        res_upd.return_value = 1
        queue = mock.Mock()
        zaqar_client = mock.Mock()
        plugin.return_value = zaqar_client
        zaqar_client.queue.return_value = queue

        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments

        result_metadata = {
            'original': 'metadata',
            'deployments': {'deploy': 'this'}
        }

        with mock.patch.object(self.ctx.session, 'refresh'):
            self.engine.software_config._push_metadata_software_deployments(
                self.ctx, '1234', 'project1')
        res_upd.assert_called_once_with(
            self.ctx, '1234', {'rsrc_metadata': result_metadata}, 1)

        plugin.assert_called_once_with('project1', mock.ANY)
        zaqar_client.queue.assert_called_once_with('6789')
        queue.post.assert_called_once_with(
            {'body': result_metadata, 'ttl': 3600})

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'signal_software_deployment')
    @mock.patch.object(swift.SwiftClientPlugin, '_create')
    def test_refresh_swift_software_deployment(self, scc, ssd):
        temp_url = ('http://192.0.2.1/v1/AUTH_a/b/c'
                    '?temp_url_sig=ctemp_url_expires=1234')
        container = 'b'
        object_name = 'c'

        config = self._create_software_config(inputs=[
            {
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'TEMP_URL_SIGNAL'
            }, {
                'name': 'deploy_signal_id',
                'type': 'String',
                'value': temp_url
            }
        ])

        timeutils.set_time_override(
            datetime.datetime(2013, 1, 23, 22, 48, 5, 0))
        self.addCleanup(timeutils.clear_time_override)
        now = timeutils.utcnow()
        then = now - datetime.timedelta(0, 60)

        last_modified_1 = 'Wed, 23 Jan 2013 22:47:05 GMT'
        last_modified_2 = 'Wed, 23 Jan 2013 22:48:05 GMT'

        sc = mock.MagicMock()
        headers = {
            'last-modified': last_modified_1
        }
        sc.head_object.return_value = headers
        sc.get_object.return_value = (headers, '{"foo": "bar"}')
        scc.return_value = sc

        deployment = self._create_software_deployment(
            status='IN_PROGRESS', config_id=config['id'])

        deployment_id = six.text_type(deployment['id'])
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)

        # poll with missing object
        swift_exc = swift.SwiftClientPlugin.exceptions_module
        sc.head_object.side_effect = swift_exc.ClientException(
            'Not found', http_status=404)

        self.assertEqual(
            sd,
            self.engine.software_config._refresh_swift_software_deployment(
                self.ctx, sd, temp_url))
        sc.head_object.assert_called_once_with(container, object_name)
        # no call to get_object or signal_last_modified
        self.assertEqual([], sc.get_object.mock_calls)
        self.assertEqual([], ssd.mock_calls)

        # poll with other error
        sc.head_object.side_effect = swift_exc.ClientException(
            'Ouch', http_status=409)
        self.assertRaises(
            swift_exc.ClientException,
            self.engine.software_config._refresh_swift_software_deployment,
            self.ctx,
            sd,
            temp_url)
        # no call to get_object or signal_last_modified
        self.assertEqual([], sc.get_object.mock_calls)
        self.assertEqual([], ssd.mock_calls)
        sc.head_object.side_effect = None

        # first poll populates data signal_last_modified
        self.engine.software_config._refresh_swift_software_deployment(
            self.ctx, sd, temp_url)
        sc.head_object.assert_called_with(container, object_name)
        sc.get_object.assert_called_once_with(container, object_name)
        # signal_software_deployment called with signal
        ssd.assert_called_once_with(self.ctx, deployment_id, {u"foo": u"bar"},
                                    then.isoformat())

        # second poll updated_at populated with first poll last-modified
        software_deployment_object.SoftwareDeployment.update_by_id(
            self.ctx, deployment_id, {'updated_at': then})
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.assertEqual(then, sd.updated_at)
        self.engine.software_config._refresh_swift_software_deployment(
            self.ctx, sd, temp_url)
        sc.get_object.assert_called_once_with(container, object_name)
        # signal_software_deployment has not been called again
        ssd.assert_called_once_with(self.ctx, deployment_id, {"foo": "bar"},
                                    then.isoformat())

        # third poll last-modified changed, new signal
        headers['last-modified'] = last_modified_2
        sc.head_object.return_value = headers
        sc.get_object.return_value = (headers, '{"bar": "baz"}')
        self.engine.software_config._refresh_swift_software_deployment(
            self.ctx, sd, temp_url)

        # two calls to signal_software_deployment, for then and now
        self.assertEqual(2, len(ssd.mock_calls))
        ssd.assert_called_with(self.ctx, deployment_id, {"bar": "baz"},
                               now.isoformat())

        # four polls result in only two signals, for then and now
        software_deployment_object.SoftwareDeployment.update_by_id(
            self.ctx, deployment_id, {'updated_at': now})
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            self.ctx, deployment_id)
        self.engine.software_config._refresh_swift_software_deployment(
            self.ctx, sd, temp_url)
        self.assertEqual(2, len(ssd.mock_calls))

    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'signal_software_deployment')
    @mock.patch.object(service_software_config.SoftwareConfigService,
                       'metadata_software_deployments')
    @mock.patch.object(db_api, 'resource_update')
    @mock.patch.object(db_api, 'resource_get_by_physical_resource_id')
    @mock.patch.object(zaqar.ZaqarClientPlugin, 'create_for_tenant')
    def test_refresh_zaqar_software_deployment(self, plugin, res_get, res_upd,
                                               md_sd, ssd):
        rs = mock.Mock()
        rs.rsrc_metadata = {}
        rs.id = '1234'
        rs.atomic_key = 1
        rd1 = mock.Mock()
        rd1.key = 'user'
        rd1.value = 'user1'
        rd2 = mock.Mock()
        rd2.key = 'password'
        rd2.decrypt_method, rd2.value = crypt.encrypt('pass1')
        rs.data = [rd1, rd2]
        res_get.return_value = rs

        res_upd.return_value = 1
        deployments = {'deploy': 'this'}
        md_sd.return_value = deployments
        config = self._create_software_config(inputs=[
            {
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'ZAQAR_SIGNAL'
            }, {
                'name': 'deploy_queue_id',
                'type': 'String',
                'value': '6789'
            }
        ])

        queue = mock.Mock()
        zaqar_client = mock.Mock()
        plugin.return_value = zaqar_client
        zaqar_client.queue.return_value = queue
        queue.pop.return_value = [mock.Mock(body='ok')]

        with mock.patch.object(self.ctx.session, 'refresh'):
            deployment = self._create_software_deployment(
                status='IN_PROGRESS', config_id=config['id'])

        deployment_id = deployment['id']
        self.assertEqual(
            deployment,
            self.engine.show_software_deployment(self.ctx, deployment_id))

        zaqar_client.queue.assert_called_once_with('6789')
        queue.pop.assert_called_once_with()
        ssd.assert_called_once_with(self.ctx, deployment_id, 'ok', None)


class SoftwareConfigIOSchemaTest(common.HeatTestCase):
    def test_input_config_empty(self):
        name = 'foo'
        inp = swc_io.InputConfig(name=name)
        self.assertIsNone(inp.default())
        self.assertIs(False, inp.replace_on_change())
        self.assertEqual(name, inp.name())
        self.assertEqual({'name': name, 'type': 'String'}, inp.as_dict())
        self.assertEqual((name, None), inp.input_data())

    def test_input_config(self):
        name = 'bar'
        inp = swc_io.InputConfig(name=name, description='test', type='Number',
                                 default=0, replace_on_change=True)
        self.assertEqual(0, inp.default())
        self.assertIs(True, inp.replace_on_change())
        self.assertEqual(name, inp.name())
        self.assertEqual({'name': name, 'type': 'Number',
                          'description': 'test', 'default': 0,
                          'replace_on_change': True},
                         inp.as_dict())
        self.assertEqual((name, None), inp.input_data())

    def test_input_config_value(self):
        name = 'baz'
        inp = swc_io.InputConfig(name=name, type='Number',
                                 default=0, value=42)
        self.assertEqual(0, inp.default())
        self.assertIs(False, inp.replace_on_change())
        self.assertEqual(name, inp.name())
        self.assertEqual({'name': name, 'type': 'Number',
                          'default': 0, 'value': 42},
                         inp.as_dict())
        self.assertEqual((name, 42), inp.input_data())

    def test_input_config_no_name(self):
        self.assertRaises(ValueError, swc_io.InputConfig, type='String')

    def test_input_config_extra_key(self):
        self.assertRaises(ValueError, swc_io.InputConfig,
                          name='test', bogus='wat')

    def test_input_types(self):
        swc_io.InputConfig(name='str', type='String').as_dict()
        swc_io.InputConfig(name='num', type='Number').as_dict()
        swc_io.InputConfig(name='list', type='CommaDelimitedList').as_dict()
        swc_io.InputConfig(name='json', type='Json').as_dict()
        swc_io.InputConfig(name='bool', type='Boolean').as_dict()

        self.assertRaises(ValueError, swc_io.InputConfig,
                          name='bogus', type='BogusType')

    def test_output_config_empty(self):
        name = 'foo'
        outp = swc_io.OutputConfig(name=name)
        self.assertEqual(name, outp.name())
        self.assertEqual({'name': name, 'type': 'String',
                          'error_output': False},
                         outp.as_dict())

    def test_output_config(self):
        name = 'bar'
        outp = swc_io.OutputConfig(name=name, description='test',
                                   type='Json', error_output=True)
        self.assertEqual(name, outp.name())
        self.assertIs(True, outp.error_output())
        self.assertEqual({'name': name, 'type': 'Json',
                          'description': 'test', 'error_output': True},
                         outp.as_dict())

    def test_output_config_no_name(self):
        self.assertRaises(ValueError, swc_io.OutputConfig, type='String')

    def test_output_config_extra_key(self):
        self.assertRaises(ValueError, swc_io.OutputConfig,
                          name='test', bogus='wat')

    def test_output_types(self):
        swc_io.OutputConfig(name='str', type='String').as_dict()
        swc_io.OutputConfig(name='num', type='Number').as_dict()
        swc_io.OutputConfig(name='list', type='CommaDelimitedList').as_dict()
        swc_io.OutputConfig(name='json', type='Json').as_dict()
        swc_io.OutputConfig(name='bool', type='Boolean').as_dict()

        self.assertRaises(ValueError, swc_io.OutputConfig,
                          name='bogus', type='BogusType')

    def test_check_io_schema_empty_list(self):
        swc_io.check_io_schema_list([])

    def test_check_io_schema_string(self):
        self.assertRaises(TypeError, swc_io.check_io_schema_list, '')

    def test_check_io_schema_dict(self):
        self.assertRaises(TypeError, swc_io.check_io_schema_list, {})

    def test_check_io_schema_list_dict(self):
        swc_io.check_io_schema_list([{'name': 'foo'}])

    def test_check_io_schema_list_string(self):
        self.assertRaises(TypeError, swc_io.check_io_schema_list, ['foo'])

    def test_check_io_schema_list_list(self):
        self.assertRaises(TypeError, swc_io.check_io_schema_list, [['foo']])

    def test_check_io_schema_list_none(self):
        self.assertRaises(TypeError, swc_io.check_io_schema_list, [None])

    def test_check_io_schema_list_mixed(self):
        self.assertRaises(TypeError, swc_io.check_io_schema_list,
                          [{'name': 'foo'}, ('name', 'bar')])

    def test_input_config_value_json_default(self):
        name = 'baz'
        inp = swc_io.InputConfig(name=name, type='Json',
                                 default={'a': 1}, value=42)
        self.assertEqual({'a': 1}, inp.default())

    def test_input_config_value_default_coerce(self):
        name = 'baz'
        inp = swc_io.InputConfig(name=name, type='Number',
                                 default='0')
        self.assertEqual(0, inp.default())

    def test_input_config_value_ignore_string(self):
        name = 'baz'
        inp = swc_io.InputConfig(name=name, type='Number',
                                 default='')

        self.assertEqual({'type': 'Number', 'name': 'baz', 'default': ''},
                         inp.as_dict())
