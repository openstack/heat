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

import copy
import mock
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import parser
from heat.engine.resources.software_config import software_deployment as sd
from heat.engine import rsrc_defn
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import utils


class SoftwareDeploymentTest(HeatTestCase):

    template = {
        'HeatTemplateFormatVersion': '2012-12-12',
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

    template_with_server = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': 'server',
                    'config': '48e8ade1-9196-42d5-89a2-f709fde42632',
                    'input_values': {'foo': 'bar'},
                }
            },
            'server': {
                'Type': 'OS::Nova::Server',
                'Properties': {
                    'image': 'fedora-amd64',
                    'flavor': 'm1.small',
                    'key_name': 'heat_key'
                }
            }
        }
    }

    template_no_signal = {
        'HeatTemplateFormatVersion': '2012-12-12',
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
        'HeatTemplateFormatVersion': '2012-12-12',
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

    def test_validate(self):
        template = dict(self.template_with_server)
        props = template['Resources']['server']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        self._create_stack(self.template_with_server)
        sd = self.deployment
        sd.validate()
        server = self.stack['server']
        self.assertTrue(server.user_data_software_config())

    def test_validate_failed(self):
        template = dict(self.template_with_server)
        props = template['Resources']['server']['Properties']
        props['user_data_format'] = 'RAW'
        self._create_stack(template)
        sd = self.deployment
        err = self.assertRaises(exception.StackValidationFailed, sd.validate)
        self.assertEqual("Resource server's property "
                         "user_data_format should be set to "
                         "SOFTWARE_CONFIG since there are "
                         "software deployments on it.", six.text_type(err))

    def test_resource_mapping(self):
        self._create_stack(self.template)
        self.assertIsInstance(self.deployment, sd.SoftwareDeployment)

    def mock_software_config(self):
        sc = mock.MagicMock()
        config = {
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
        sc.to_dict.return_value = config
        sc.group = 'Test::Group'
        sc.config = config['config']
        self.software_configs.get.return_value = sc
        return sc

    def mock_software_component(self):
        sc = mock.MagicMock()
        config = {
            'id': '48e8ade1-9196-42d5-89a2-f709fde42632',
            'group': 'component',
            'name': 'myconfig',
            'config': {
                'configs': [
                    {
                        'actions': ['CREATE'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['DELETE'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['UPDATE'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['SUSPEND'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['RESUME'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    }
                ]
            },
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
        sc.to_dict.return_value = config
        sc.group = 'component'
        sc.config = config['config']
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

    def test_handle_create_for_component(self):
        self._create_stack(self.template_no_signal)

        self.mock_software_component()
        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()

        self.deployment.handle_create()

        self.assertEqual(sd.id, self.deployment.resource_id)
        self.assertEqual({
            'config': {
                'configs': [
                    {
                        'actions': ['CREATE'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['DELETE'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['UPDATE'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['SUSPEND'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    },
                    {
                        'actions': ['RESUME'],
                        'config': 'the config',
                        'tool': 'a_tool'
                    }
                ]
            },
            'group': 'component',
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
            'Deployment to server failed: something wrong', six.text_type(err))

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

        self.mock_software_config()

        derived_sc = self.mock_derived_software_config()
        sd = self.mock_deployment()
        rsrc = self.stack['deployment_mysql']

        self.deployments.get.return_value = sd
        sd.update.return_value = None
        self.deployment.resource_id = sd.id
        config_id = '0ff2e903-78d7-4cca-829e-233af3dae705'
        prop_diff = {'config': config_id}
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

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

    def test_handle_signal_ok_zero(self):
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
        ret = self.deployment.handle_signal(details)
        self.assertEqual('deployment succeeded', ret)
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

    def test_handle_signal_ok_str_zero(self):
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
            'deploy_status_code': '0'
        }
        ret = self.deployment.handle_signal(details)
        self.assertEqual('deployment succeeded', ret)
        args = sd.update.call_args[1]
        self.assertEqual({
            'output_values': {
                'foo': 'bar',
                'deploy_status_code': '0',
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
        ret = self.deployment.handle_signal(details)
        self.assertEqual('deployment failed', ret)
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

        # Test bug 1332355, where details contains a translateable message
        details = {'failed': _('need more memory.')}
        self.deployment.handle_signal(details)
        args = sd.update.call_args[1]
        self.assertEqual({
            'output_values': {
                'deploy_status_code': None,
                'deploy_stderr': None,
                'deploy_stdout': None,
                'failed': 'need more memory.'
            },
            'status': 'FAILED',
            'status_reason': 'failed : need more memory.'
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
            six.text_type(err))

    def test_handle_action(self):
        self._create_stack(self.template)

        self.mock_software_config()

        for action in ('DELETE', 'SUSPEND', 'RESUME'):
            self.assertIsNone(self.deployment._handle_action(action))
        for action in ('CREATE', 'UPDATE'):
            self.assertIsNotNone(self.deployment._handle_action(action))

    def test_handle_action_for_component(self):
        self._create_stack(self.template)

        self.mock_software_component()

        for action in ('CREATE', 'UPDATE', 'DELETE', 'SUSPEND', 'RESUME'):
            self.assertIsNotNone(self.deployment._handle_action(action))


class SoftwareDeploymentsTest(HeatTestCase):

    template = {
        'heat_template_version': '2013-05-23',
        'resources': {
            'deploy_mysql': {
                'type': 'OS::Heat::SoftwareDeployments',
                'properties': {
                    'config': 'config_uuid',
                    'servers': {'server1': 'uuid1', 'server2': 'uuid2'},
                    'input_values': {'foo': 'bar'},
                    'name': '10_config'
                }
            }
        }
    }

    def setUp(self):
        HeatTestCase.setUp(self)
        heat = mock.MagicMock()
        self.deployments = heat.return_value.software_deployments

    def test_build_resource_definition(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeployments('test', snip, stack)
        expect = {
            'type': 'OS::Heat::SoftwareDeployment',
            'properties': {
                'actions': ['CREATE', 'UPDATE'],
                'config': 'config_uuid',
                'input_values': {'foo': 'bar'},
                'name': '10_config',
                'signal_transport': 'CFN_SIGNAL'
            }
        }
        self.assertEqual(
            expect, resg._build_resource_definition())
        self.assertEqual(
            expect, resg._build_resource_definition(include_all=True))

    def test_resource_names(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeployments('test', snip, stack)
        self.assertEqual(
            set(('server1', 'server2')),
            set(resg._resource_names())
        )

        self.assertEqual(
            set(('s1', 's2', 's3')),
            set(resg._resource_names({
                'servers': {'s1': 'u1', 's2': 'u2', 's3': 'u3'}}))
        )

    def test_assemble_nested(self):
        """
        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeployments('test', snip, stack)
        templ = {
            "heat_template_version": "2013-05-23",
            "resources": {
                "server1": {
                    'type': 'OS::Heat::SoftwareDeployment',
                    'properties': {
                        'server': 'uuid1',
                        'actions': ['CREATE', 'UPDATE'],
                        'config': 'config_uuid',
                        'input_values': {'foo': 'bar'},
                        'name': '10_config',
                        'signal_transport': 'CFN_SIGNAL'
                    }
                },
                "server2": {
                    'type': 'OS::Heat::SoftwareDeployment',
                    'properties': {
                        'server': 'uuid2',
                        'actions': ['CREATE', 'UPDATE'],
                        'config': 'config_uuid',
                        'input_values': {'foo': 'bar'},
                        'name': '10_config',
                        'signal_transport': 'CFN_SIGNAL'
                    }
                }
            }
        }

        self.assertEqual(templ, resg._assemble_nested(['server1', 'server2']))

    def test_attributes(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeployments('test', snip, stack)
        nested = self.patchobject(resg, 'nested')
        server1 = mock.MagicMock()
        server2 = mock.MagicMock()
        nested.return_value = {
            'server1': server1,
            'server2': server2
        }

        server1.FnGetAtt.return_value = 'Thing happened on server1'
        server2.FnGetAtt.return_value = 'ouch'
        self.assertEqual({
            'server1': 'Thing happened on server1',
            'server2': 'ouch'
        }, resg.FnGetAtt('deploy_stdouts'))

        server1.FnGetAtt.return_value = ''
        server2.FnGetAtt.return_value = 'Its gone Pete Tong'
        self.assertEqual({
            'server1': '',
            'server2': 'Its gone Pete Tong'
        }, resg.FnGetAtt('deploy_stderrs'))

        server1.FnGetAtt.return_value = 0
        server2.FnGetAtt.return_value = 1
        self.assertEqual({
            'server1': 0,
            'server2': 1
        }, resg.FnGetAtt('deploy_status_codes'))

        server1.FnGetAtt.assert_has_calls([
            mock.call('deploy_stdout'),
            mock.call('deploy_stderr'),
            mock.call('deploy_status_code'),
        ])
