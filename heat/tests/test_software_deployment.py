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

from heatclient.exc import HTTPNotFound
import mock

from heat.common import exception
from heat.engine import parser
from heat.engine.resources.software_config import software_deployment as sd
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import utils


class SoftwareDeploymentTest(HeatTestCase):

    template = {
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                    'config': '48e8ade1-9196-42d5-89a2-f709fde42632',
                    'input_values': {'foo': 'bar'},
                }
            }
        }
    }

    template_no_signal = {
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                    'config': '48e8ade1-9196-42d5-89a2-f709fde42632',
                    'input_values': {'foo': 'bar', 'bink': 'bonk'},
                    'signal_transport': 'NO_SIGNAL',
                    'name': '00_run_me_first'
                }
            }
        }
    }

    template_delete_suspend_resume = {
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                    'config': '48e8ade1-9196-42d5-89a2-f709fde42632',
                    'input_values': {'foo': 'bar'},
                    'actions': ['DELETE', 'SUSPEND', 'RESUME'],
                }
            }
        }
    }

    def setUp(self):
        super(SoftwareDeploymentTest, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()

    def _create_stack(self, tmpl):
        self.stack = parser.Stack(
            self.ctx, 'software_deployment_test_stack',
            template.Template(tmpl),
            stack_id='42f6f66b-631a-44e7-8d01-e22fb54574a9',
            stack_user_project_id='65728b74-cfe7-4f17-9c15-11d4f686e591'
        )

        self.patchobject(sd.SoftwareDeployment, '_create_user')
        self.patchobject(sd.SoftwareDeployment, '_create_keypair')
        self.patchobject(sd.SoftwareDeployment, '_delete_user')
        self.patchobject(sd.SoftwareDeployment, '_delete_signed_url')
        get_signed_url = self.patchobject(
            sd.SoftwareDeployment, '_get_signed_url')
        get_signed_url.return_value = 'http://192.0.2.2/signed_url'

        self.deployment = self.stack['deployment_mysql']
        heat = mock.MagicMock()
        self.deployment.heat = heat
        self.deployments = heat.return_value.software_deployments
        self.software_configs = heat.return_value.software_configs

    def test_resource_mapping(self):
        self._create_stack(self.template)
        self.assertIsInstance(self.deployment, sd.SoftwareDeployment)

    def mock_software_config(self):
        sc = mock.MagicMock()
        sc.to_dict.return_value = {
            'id': '48e8ade1-9196-42d5-89a2-f709fde42632',
            'group': 'Test::Group',
            'name': 'myconfig',
            'config': 'the config',
            'options': {},
            'inputs': [{
                'name': 'foo',
                'type': 'String',
                'default': 'baa',
            }, {
                'name': 'bar',
                'type': 'String',
                'default': 'baz',
            }],
            'outputs': [],
        }
        self.software_configs.get.return_value = sc
        return sc

    def mock_derived_software_config(self):
        sc = mock.MagicMock()
        sc.id = '9966c8e7-bc9c-42de-aa7d-f2447a952cb2'
        self.software_configs.create.return_value = sc
        return sc

    def mock_deployment(self):
        sd = mock.MagicMock()
        sd.id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.deployments.create.return_value = sd
        return sd

    def test_handle_create(self):
        self._create_stack(self.template_no_signal)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()

        self.deployment.handle_create()

        self.assertEqual(sd.id, self.deployment.resource_id)
        self.assertEqual({
            'config': 'the config',
            'group': 'Test::Group',
            'name': '00_run_me_first',
            'inputs': [{
                'default': 'baa',
                'name': 'foo',
                'type': 'String',
                'value': 'bar'
            }, {
                'default': 'baz',
                'name': 'bar',
                'type': 'String',
                'value': 'baz'
            }, {
                'name': 'bink',
                'type': 'String',
                'value': 'bonk'
            }, {
                'description': 'ID of the server being deployed to',
                'name': 'deploy_server_id',
                'type': 'String',
                'value': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0'
            }, {
                'description': 'Name of the current action being deployed',
                'name': 'deploy_action',
                'type': 'String',
                'value': 'CREATE'
            }, {
                'description': 'ID of the stack this deployment belongs to',
                'name': 'deploy_stack_id',
                'type': 'String',
                'value': ('software_deployment_test_stack'
                          '/42f6f66b-631a-44e7-8d01-e22fb54574a9')
            }, {
                'description': 'Name of this deployment resource in the stack',
                'name': 'deploy_resource_name',
                'type': 'String',
                'value': 'deployment_mysql'
            }],
            'options': {},
            'outputs': []
        }, self.software_configs.create.call_args[1])

        self.assertEqual(
            {'action': 'CREATE',
             'config_id': derived_sc.id,
             'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
             'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
             'status': 'COMPLETE',
             'status_reason': 'Not waiting for outputs signal'},
            self.deployments.create.call_args[1])

    def test_handle_create_do_not_wait(self):
        self._create_stack(self.template)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()

        self.deployment.handle_create()
        self.assertEqual(sd.id, self.deployment.resource_id)
        args = self.deployments.create.call_args[1]
        self.assertEqual(
            {'action': 'CREATE',
             'config_id': derived_sc.id,
             'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
             'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
             'status': 'IN_PROGRESS',
             'status_reason': 'Deploy data available'},
            args)

    def test_check_create_complete(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.status = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_create_complete(sd))
        sd.status = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_create_complete(sd))

    def test_check_update_complete(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.status = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_update_complete(sd))
        sd.status = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_update_complete(sd))

    def test_check_suspend_complete(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.status = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_suspend_complete(sd))
        sd.status = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_suspend_complete(sd))

    def test_check_resume_complete(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.status = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_resume_complete(sd))
        sd.status = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_resume_complete(sd))

    def test_check_create_complete_error(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.status = self.deployment.FAILED
        sd.status_reason = 'something wrong'
        err = self.assertRaises(
            exception.Error, self.deployment.check_create_complete, sd)
        self.assertEqual(
            'Deployment to server failed: something wrong', str(err))

    def test_handle_delete(self):
        self._create_stack(self.template)
        sd = self.mock_deployment()
        self.deployments.get.return_value = sd

        self.deployment.resource_id = sd.id
        self.deployment.handle_delete()

        self.assertEqual([], sd.delete.call_args)

    def test_delete_complete(self):
        self._create_stack(self.template_delete_suspend_resume)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()

        self.deployment.resource_id = sd.id
        self.deployments.delete.return_value = None

        self.deployments.get.return_value = sd
        sd.update.return_value = None
        self.assertEqual(sd, self.deployment.handle_delete())
        args = sd.update.call_args[1]
        self.assertEqual({
            'action': 'DELETE',
            'config_id': derived_sc.id,
            'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
            'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
            'status': 'IN_PROGRESS',
            'status_reason': 'Deploy data available'
        }, args)

        self.assertFalse(self.deployment.check_delete_complete(sd))

        sd.status = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_delete_complete(sd))

    def test_handle_delete_notfound(self):
        self._create_stack(self.template)
        deployment_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.deployment.resource_id = deployment_id

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()
        sd.config_id = derived_sc.id
        self.deployments.get.return_value = sd

        sd.delete.side_effect = HTTPNotFound()
        self.software_configs.delete.side_effect = HTTPNotFound()
        self.assertIsNone(self.deployment.handle_delete())
        self.assertEqual(
            (derived_sc.id,), self.software_configs.delete.call_args[0])

    def test_handle_delete_none(self):
        self._create_stack(self.template)
        deployment_id = None
        self.deployment.resource_id = deployment_id
        self.assertIsNone(self.deployment.handle_delete())

    def test_check_delete_complete_none(self):
        self._create_stack(self.template)
        self.assertTrue(self.deployment.check_delete_complete())

    def test_handle_update(self):
        self._create_stack(self.template)

        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()

        self.deployments.get.return_value = sd
        sd.update.return_value = None
        self.deployment.resource_id = sd.id
        config_id = '0ff2e903-78d7-4cca-829e-233af3dae705'
        prop_diff = {'config': config_id}
        snippet = {
            'Properties': {
                'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                'config': config_id,
            }
        }

        self.deployment.handle_update(
            json_snippet=snippet, tmpl_diff=None, prop_diff=prop_diff)
        self.assertEqual(
            (config_id,), self.software_configs.get.call_args[0])

        args = self.deployments.get.call_args[0]
        self.assertEqual(1, len(args))
        self.assertIn(sd.id, args)
        args = sd.update.call_args[1]
        self.assertEqual(derived_sc.id, args['config_id'])

    def test_handle_suspend_resume(self):
        self._create_stack(self.template_delete_suspend_resume)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()

        self.deployments.get.return_value = sd
        sd.update.return_value = None
        self.deployment.resource_id = sd.id

        # first, handle the suspend
        self.deployment.handle_suspend()

        args = sd.update.call_args[1]
        self.assertEqual({
            'action': 'SUSPEND',
            'config_id': derived_sc.id,
            'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
            'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
            'status': 'IN_PROGRESS',
            'status_reason': 'Deploy data available'
        }, args)

        sd.status = 'IN_PROGRESS'
        self.assertFalse(self.deployment.check_suspend_complete(sd))

        sd.status = 'COMPLETE'
        self.assertTrue(self.deployment.check_suspend_complete(sd))

        # now, handle the resume
        self.deployment.handle_resume()

        args = sd.update.call_args[1]
        self.assertEqual({
            'action': 'RESUME',
            'config_id': derived_sc.id,
            'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
            'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
            'status': 'IN_PROGRESS',
            'status_reason': 'Deploy data available'
        }, args)

        sd.status = 'IN_PROGRESS'
        self.assertFalse(self.deployment.check_resume_complete(sd))

        sd.status = 'COMPLETE'
        self.assertTrue(self.deployment.check_resume_complete(sd))

    def test_handle_signal(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sc = mock.MagicMock()
        sc.outputs = [{'name': 'foo'},
                      {'name': 'foo2'},
                      {'name': 'failed',
                       'error_output': True}]
        sd.output_values = {}
        sd.status = self.deployment.IN_PROGRESS
        sd.update.return_value = None
        self.deployments.get.return_value = sd
        self.software_configs.get.return_value = sc
        details = {
            'foo': 'bar',
            'deploy_status_code': 0
        }
        self.deployment.handle_signal(details)
        args = sd.update.call_args[1]
        self.assertEqual({
            'output_values': {
                'foo': 'bar',
                'deploy_status_code': 0,
                'deploy_stderr': None,
                'deploy_stdout': None
            },
            'status': 'COMPLETE',
            'status_reason': 'Outputs received'
        }, args)

    def test_handle_signal_failed(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sc = mock.MagicMock()
        sc.outputs = [{'name': 'foo'},
                      {'name': 'foo2'},
                      {'name': 'failed',
                       'error_output': True}]
        sd.output_values = {}
        sd.status = self.deployment.IN_PROGRESS
        sd.update.return_value = None
        self.deployments.get.return_value = sd
        self.software_configs.get.return_value = sc
        details = {'failed': 'no enough memory found.'}
        self.deployment.handle_signal(details)
        args = sd.update.call_args[1]
        self.assertEqual({
            'output_values': {
                'deploy_status_code': None,
                'deploy_stderr': None,
                'deploy_stdout': None,
                'failed': 'no enough memory found.'
            },
            'status': 'FAILED',
            'status_reason': 'failed : no enough memory found.'
        }, args)

    def test_handle_status_code_failed(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.outputs = []
        sd.output_values = {}
        sd.status = self.deployment.IN_PROGRESS
        sd.update.return_value = None
        self.deployments.get.return_value = sd
        details = {
            'deploy_stdout': 'A thing happened',
            'deploy_stderr': 'Then it broke',
            'deploy_status_code': -1
        }
        self.deployment.handle_signal(details)
        args = sd.update.call_args[1]
        self.assertEqual({
            'output_values': {
                'deploy_stdout': 'A thing happened',
                'deploy_stderr': 'Then it broke',
                'deploy_status_code': -1
            },
            'status': 'FAILED',
            'status_reason': ('deploy_status_code : Deployment exited '
                              'with non-zero status code: -1')
        }, args)

    def test_handle_signal_not_waiting(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.status = self.deployment.COMPLETE
        self.deployments.get.return_value = sd
        details = None
        self.assertIsNone(self.deployment.handle_signal(details))

    def test_fn_get_att(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.outputs = [{'name': 'failed', 'error_output': True},
                      {'name': 'foo'}]
        sd.output_values = {
            'foo': 'bar',
            'deploy_stdout': 'A thing happened',
            'deploy_stderr': 'Extraneous logging',
            'deploy_status_code': 0
        }
        self.deployments.get.return_value = sd
        self.assertEqual('bar', self.deployment.FnGetAtt('foo'))
        self.assertEqual('A thing happened',
                         self.deployment.FnGetAtt('deploy_stdout'))
        self.assertEqual('Extraneous logging',
                         self.deployment.FnGetAtt('deploy_stderr'))
        self.assertEqual(0, self.deployment.FnGetAtt('deploy_status_code'))

    def test_fn_get_att_error(self):
        self._create_stack(self.template)
        sd = mock.MagicMock()
        sd.outputs = []
        sd.output_values = {'foo': 'bar'}
        err = self.assertRaises(
            exception.InvalidTemplateAttribute,
            self.deployment.FnGetAtt, 'foo2')
        self.assertEqual(
            'The Referenced Attribute (deployment_mysql foo2) is incorrect.',
            str(err))

    def test_handle_action(self):
        self._create_stack(self.template)
        for action in ('DELETE', 'SUSPEND', 'RESUME'):
            self.assertIsNone(self.deployment._handle_action(action))
        for action in ('CREATE', 'UPDATE'):
            self.assertIsNotNone(self.deployment._handle_action(action))
