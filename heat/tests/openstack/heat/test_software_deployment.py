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

import copy

import datetime
import re
import uuid

import mock
import six

from oslo_utils import timeutils

from heat.common import exception as exc
from heat.common.i18n import _
from heat.engine.clients.os import nova
from heat.engine.clients.os import swift
from heat.engine.clients.os import zaqar
from heat.engine.resources.openstack.heat import software_deployment as sd
from heat.engine import rsrc_defn
from heat.engine import stack as parser
from heat.engine import template
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests import utils


class SoftwareDeploymentTest(common.HeatTestCase):

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

    template_with_timeout = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                    'config': '48e8ade1-9196-42d5-89a2-f709fde42632',
                    'input_values': {'foo': 'bar'},
                    'timeout': 5,
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

    template_temp_url_signal = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                    'config': '48e8ade1-9196-42d5-89a2-f709fde42632',
                    'input_values': {'foo': 'bar', 'bink': 'bonk'},
                    'signal_transport': 'TEMP_URL_SIGNAL',
                    'name': '00_run_me_first'
                }
            }
        }
    }

    template_zaqar_signal = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                    'config': '48e8ade1-9196-42d5-89a2-f709fde42632',
                    'input_values': {'foo': 'bar', 'bink': 'bonk'},
                    'signal_transport': 'ZAQAR_SIGNAL',
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

    template_no_config = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {
                    'server': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
                    'input_values': {'foo': 'bar', 'bink': 'bonk'},
                    'signal_transport': 'NO_SIGNAL',
                }
            }
        }
    }

    template_no_server = {
        'HeatTemplateFormatVersion': '2012-12-12',
        'Resources': {
            'deployment_mysql': {
                'Type': 'OS::Heat::SoftwareDeployment',
                'Properties': {}
            }
        }
    }

    def setUp(self):
        super(SoftwareDeploymentTest, self).setUp()
        self.ctx = utils.dummy_context()

    def _create_stack(self, tmpl, cache_data=None):
        self.stack = parser.Stack(
            self.ctx, 'software_deployment_test_stack',
            template.Template(tmpl),
            stack_id='42f6f66b-631a-44e7-8d01-e22fb54574a9',
            stack_user_project_id='65728b74-cfe7-4f17-9c15-11d4f686e591',
            cache_data=cache_data
        )

        self.patchobject(nova.NovaClientPlugin, 'get_server',
                         return_value=mock.MagicMock())
        self.patchobject(sd.SoftwareDeployment, '_create_user')
        self.patchobject(sd.SoftwareDeployment, '_create_keypair')
        self.patchobject(sd.SoftwareDeployment, '_delete_user')
        self.patchobject(sd.SoftwareDeployment, '_delete_ec2_signed_url')
        get_ec2_signed_url = self.patchobject(
            sd.SoftwareDeployment, '_get_ec2_signed_url')
        get_ec2_signed_url.return_value = 'http://192.0.2.2/signed_url'

        self.deployment = self.stack['deployment_mysql']

        self.rpc_client = mock.MagicMock()
        self.deployment._rpc_client = self.rpc_client

    def test_validate(self):
        template = dict(self.template_with_server)
        props = template['Resources']['server']['Properties']
        props['user_data_format'] = 'SOFTWARE_CONFIG'
        self._create_stack(self.template_with_server)
        sd = self.deployment
        self.assertEqual('CFN_SIGNAL', sd.properties.get('signal_transport'))
        sd.validate()

    def test_validate_without_server(self):
        stack = utils.parse_stack(self.template_no_server)
        snip = stack.t.resource_definitions(stack)['deployment_mysql']
        deployment = sd.SoftwareDeployment('deployment_mysql', snip, stack)
        err = self.assertRaises(exc.StackValidationFailed, deployment.validate)
        self.assertEqual("Property error: "
                         "Resources.deployment_mysql.Properties: "
                         "Property server not assigned", six.text_type(err))

    def test_validate_failed(self):
        template = dict(self.template_with_server)
        props = template['Resources']['server']['Properties']
        props['user_data_format'] = 'RAW'
        self._create_stack(template)
        sd = self.deployment
        err = self.assertRaises(exc.StackValidationFailed, sd.validate)
        self.assertEqual("Resource server's property "
                         "user_data_format should be set to "
                         "SOFTWARE_CONFIG since there are "
                         "software deployments on it.", six.text_type(err))

    def mock_software_config(self):
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
        self.rpc_client.show_software_config.return_value = config
        return config

    def mock_software_component(self):
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
        self.rpc_client.show_software_config.return_value = config
        return config

    def mock_derived_software_config(self):
        sc = {'id': '9966c8e7-bc9c-42de-aa7d-f2447a952cb2'}
        self.rpc_client.create_software_config.return_value = sc
        return sc

    def mock_deployment(self):
        mock_sd = {
            'config_id': '9966c8e7-bc9c-42de-aa7d-f2447a952cb2',
            rpc_api.SOFTWARE_DEPLOYMENT_CREATION_TIME: datetime.datetime.now(),
            rpc_api.SOFTWARE_DEPLOYMENT_ACTION: 'CREATE',
        }
        self.rpc_client.create_software_deployment.return_value = mock_sd
        return mock_sd

    def test_handle_create(self):
        self._create_stack(self.template_no_signal)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        self.mock_deployment()

        self.deployment.handle_create()

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
            }, {
                'description': ('How the server should signal to heat with '
                                'the deployment output values.'),
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'NO_SIGNAL'
            }],
            'options': {},
            'outputs': []
        }, self.rpc_client.create_software_config.call_args[1])

        self.assertEqual(
            {'action': 'CREATE',
             'config_id': derived_sc['id'],
             'deployment_id': self.deployment.resource_id,
             'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
             'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
             'status': 'COMPLETE',
             'status_reason': 'Not waiting for outputs signal'},
            self.rpc_client.create_software_deployment.call_args[1])

    def test_handle_create_without_config(self):
        self._create_stack(self.template_no_config)
        self.mock_deployment()
        derived_sc = self.mock_derived_software_config()
        self.deployment.handle_create()

        call_arg = self.rpc_client.create_software_config.call_args[1]
        call_arg['inputs'] = sorted(
            call_arg['inputs'], key=lambda k: k['name'])
        self.assertEqual({
            'config': '',
            'group': 'Heat::Ungrouped',
            'name': self.deployment.physical_resource_name(),
            'inputs': [{
                'name': 'bink',
                'type': 'String',
                'value': 'bonk'
            }, {
                'description': 'Name of the current action being deployed',
                'name': 'deploy_action',
                'type': 'String',
                'value': 'CREATE'
            }, {
                'description': 'Name of this deployment resource in the stack',
                'name': 'deploy_resource_name',
                'type': 'String',
                'value': 'deployment_mysql'
            }, {
                'description': 'ID of the server being deployed to',
                'name': 'deploy_server_id',
                'type': 'String',
                'value': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0'
            }, {
                'description': ('How the server should signal to heat with '
                                'the deployment output values.'),
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'NO_SIGNAL'
            }, {
                'description': 'ID of the stack this deployment belongs to',
                'name': 'deploy_stack_id',
                'type': 'String',
                'value': ('software_deployment_test_stack'
                          '/42f6f66b-631a-44e7-8d01-e22fb54574a9')
            }, {
                'name': 'foo',
                'type': 'String',
                'value': 'bar'
            }],
            'options': None,
            'outputs': None
        }, call_arg)

        self.assertEqual(
            {'action': 'CREATE',
             'config_id': derived_sc['id'],
             'deployment_id': self.deployment.resource_id,
             'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
             'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
             'status': 'COMPLETE',
             'status_reason': 'Not waiting for outputs signal'},
            self.rpc_client.create_software_deployment.call_args[1])

    def test_handle_create_for_component(self):
        self._create_stack(self.template_no_signal)

        self.mock_software_component()
        derived_sc = self.mock_derived_software_config()
        self.mock_deployment()

        self.deployment.handle_create()

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
            }, {
                'description': ('How the server should signal to heat with '
                                'the deployment output values.'),
                'name': 'deploy_signal_transport',
                'type': 'String',
                'value': 'NO_SIGNAL'
            }],
            'options': {},
            'outputs': []
        }, self.rpc_client.create_software_config.call_args[1])

        self.assertEqual(
            {'action': 'CREATE',
             'config_id': derived_sc['id'],
             'deployment_id': self.deployment.resource_id,
             'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
             'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
             'status': 'COMPLETE',
             'status_reason': 'Not waiting for outputs signal'},
            self.rpc_client.create_software_deployment.call_args[1])

    def test_handle_create_do_not_wait(self):
        self._create_stack(self.template)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        self.mock_deployment()

        self.deployment.handle_create()
        self.assertEqual(
            {'action': 'CREATE',
             'config_id': derived_sc['id'],
             'deployment_id': self.deployment.resource_id,
             'server_id': '9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
             'stack_user_project_id': '65728b74-cfe7-4f17-9c15-11d4f686e591',
             'status': 'IN_PROGRESS',
             'status_reason': 'Deploy data available'},
            self.rpc_client.create_software_deployment.call_args[1])

    def test_check_create_complete(self):
        self._create_stack(self.template)
        sd = self.mock_deployment()
        self.rpc_client.show_software_deployment.return_value = sd

        create_data = (sd, datetime.datetime.now())
        sd['status'] = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_create_complete(create_data))
        sd['status'] = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_create_complete(create_data))

    def test_check_create_complete_timeout(self):
        # Setup
        self._create_stack(self.template_with_timeout)
        mock_sd = self.mock_deployment()
        self.rpc_client.show_software_deployment.return_value = mock_sd

        # Test
        create_data = (mock_sd,
                       timeutils.utcnow() - datetime.timedelta(seconds=10))
        e = self.assertRaises(exc.Error,
                              self.deployment.check_create_complete,
                              create_data)

        # Verify
        self.assertIn('CREATE', e.message)
        self.assertIn('after 5s', e.message)

    def test_check_create_complete_none(self):
        self._create_stack(self.template)
        create_data = (None, datetime.datetime.now())
        self.assertTrue(self.deployment.check_create_complete(create_data))

    def test_check_update_complete(self):
        self._create_stack(self.template)
        sd = self.mock_deployment()
        self.rpc_client.show_software_deployment.return_value = sd

        update_data = (sd, datetime.datetime.now())
        sd['status'] = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_update_complete(update_data))

        sd['status'] = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_update_complete(update_data))

    def test_check_update_complete_none(self):
        self._create_stack(self.template)
        update_data = (None, datetime.datetime.now())
        self.assertTrue(self.deployment.check_update_complete(update_data))

    def test_check_update_timeout(self):
        # Setup
        self._create_stack(self.template_with_timeout)
        mock_sd = self.mock_deployment()
        mock_sd[rpc_api.SOFTWARE_DEPLOYMENT_ACTION] = 'UPDATE'
        self.rpc_client.show_software_deployment.return_value = mock_sd

        # Test
        update_data = (mock_sd,
                       timeutils.utcnow() - datetime.timedelta(seconds=10))
        e = self.assertRaises(exc.Error,
                              self.deployment.check_update_complete,
                              update_data)

        # Verify
        self.assertIn('UPDATE', e.message)
        self.assertIn('after 5s', e.message)

    def test_check_suspend_complete(self):
        self._create_stack(self.template)
        mock_sd = self.mock_deployment()
        self.rpc_client.show_software_deployment.return_value = mock_sd

        suspend_data = (mock_sd, datetime.datetime.now())

        mock_sd['status'] = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_suspend_complete(suspend_data))

        mock_sd['status'] = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_suspend_complete(suspend_data))

    def test_check_suspend_complete_none(self):
        self._create_stack(self.template)
        suspend_data = (None, datetime.datetime.now())
        self.assertTrue(self.deployment.check_suspend_complete(suspend_data))

    def test_check_suspend_complete_timeout(self):
        # Setup
        self._create_stack(self.template_with_timeout)
        mock_sd = self.mock_deployment()
        mock_sd[rpc_api.SOFTWARE_DEPLOYMENT_ACTION] = 'SUSPEND'
        self.rpc_client.show_software_deployment.return_value = mock_sd

        # Test
        suspend_data = (mock_sd,
                        timeutils.utcnow() - datetime.timedelta(seconds=10))
        e = self.assertRaises(exc.Error,
                              self.deployment.check_suspend_complete,
                              suspend_data)

        # Verify
        self.assertIn('SUSPEND', e.message)
        self.assertIn('after 5s', e.message)

    def test_check_resume_complete(self):
        self._create_stack(self.template)
        mock_sd = self.mock_deployment()
        self.rpc_client.show_software_deployment.return_value = mock_sd

        resume_data = (mock_sd, datetime.datetime.now())

        mock_sd['status'] = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_resume_complete(resume_data))

        mock_sd['status'] = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_resume_complete(resume_data))

    def test_check_resume_complete_none(self):
        self._create_stack(self.template)
        resume_data = (None, datetime.datetime.now())
        self.assertTrue(self.deployment.check_resume_complete(resume_data))

    def test_check_resume_complete_timeout(self):
        # Setup
        self._create_stack(self.template_with_timeout)
        mock_sd = self.mock_deployment()
        mock_sd[rpc_api.SOFTWARE_DEPLOYMENT_ACTION] = 'RESUME'
        self.rpc_client.show_software_deployment.return_value = mock_sd

        # Test
        resume_data = (mock_sd,
                       timeutils.utcnow() - datetime.timedelta(seconds=10))
        e = self.assertRaises(exc.Error,
                              self.deployment.check_resume_complete,
                              resume_data)

        # Verify
        self.assertIn('RESUME', e.message)
        self.assertIn('after 5s', e.message)

    def test_check_create_complete_error(self):
        self._create_stack(self.template)
        sd = {
            'status': self.deployment.FAILED,
            'status_reason': 'something wrong',
            rpc_api.SOFTWARE_DEPLOYMENT_CREATION_TIME: datetime.datetime.now(),
        }
        create_data = (sd, datetime.datetime.now())
        self.rpc_client.show_software_deployment.return_value = sd
        err = self.assertRaises(
            exc.Error, self.deployment.check_create_complete, create_data)
        self.assertEqual(
            'Deployment to server failed: something wrong', six.text_type(err))

    def test_handle_delete(self):
        self._create_stack(self.template)
        mock_sd = self.mock_deployment()
        mock_sd['server_id'] = 'b509edfb-1448-4b57-8cb1-2e31acccbb8a'
        mock_sd['status'] = self.deployment.COMPLETE
        self.rpc_client.show_software_deployment.return_value = mock_sd

        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.deployment.handle_delete()
        delete_data = (mock_sd, datetime.datetime.now())
        self.deployment.check_delete_complete(delete_data)
        self.assertEqual(
            (self.ctx, self.deployment.resource_id),
            self.rpc_client.delete_software_deployment.call_args[0])

    def test_handle_delete_resource_id_is_None(self):
        self._create_stack(self.template_delete_suspend_resume)
        self.mock_software_config()
        sd = self.mock_deployment()
        self.assertEqual(sd, self.deployment.handle_delete()[0])

    def test_delete_complete(self):
        self._create_stack(self.template_delete_suspend_resume)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        mock_sd = self.mock_deployment()
        mock_sd['server_id'] = 'b509edfb-1448-4b57-8cb1-2e31acccbb8a'

        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'

        self.rpc_client.show_software_deployment.return_value = mock_sd
        self.rpc_client.update_software_deployment.return_value = mock_sd
        self.assertEqual(mock_sd, self.deployment.handle_delete()[0])
        self.assertEqual({
            'deployment_id': 'c8a19429-7fde-47ea-a42f-40045488226c',
            'action': 'DELETE',
            'config_id': derived_sc['id'],
            'status': 'IN_PROGRESS',
            'status_reason': 'Deploy data available'},
            self.rpc_client.update_software_deployment.call_args[1])

        delete_data = (mock_sd, datetime.datetime.now())
        mock_sd['status'] = self.deployment.IN_PROGRESS
        self.assertFalse(self.deployment.check_delete_complete(delete_data))

        mock_sd['status'] = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_delete_complete(delete_data))

    def test_delete_complete_missing_server(self):
        """Tests deleting a deployment when the server disappears"""
        self._create_stack(self.template_delete_suspend_resume)

        self.mock_software_config()
        mock_sd = self.mock_deployment()
        mock_sd['server_id'] = 'b509edfb-1448-4b57-8cb1-2e31acccbb8a'

        # Simulate Nova not knowing about the server
        mock_get_server = self.patchobject(
            nova.NovaClientPlugin, 'get_server',
            side_effect=exc.EntityNotFound)

        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'

        self.rpc_client.show_software_deployment.return_value = mock_sd
        self.rpc_client.update_software_deployment.return_value = mock_sd

        delete_data = (mock_sd, datetime.datetime.now())
        mock_sd['status'] = self.deployment.COMPLETE
        self.assertTrue(self.deployment.check_delete_complete(delete_data))

        mock_get_server.assert_called_once_with(mock_sd['server_id'])

    def test_handle_delete_notfound(self):
        self._create_stack(self.template)
        deployment_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.deployment.resource_id = deployment_id

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        mock_sd = self.mock_deployment()
        mock_sd['config_id'] = derived_sc['id']
        mock_sd['server_id'] = 'b509edfb-1448-4b57-8cb1-2e31acccbb8a'
        mock_sd['status'] = self.deployment.COMPLETE
        self.rpc_client.show_software_deployment.return_value = mock_sd

        nf = exc.NotFound
        self.rpc_client.delete_software_deployment.side_effect = nf
        self.rpc_client.delete_software_config.side_effect = nf
        self.assertIsNone(self.deployment.handle_delete()[0])
        delete_data = (mock_sd, datetime.datetime.now())
        self.assertTrue(self.deployment.check_delete_complete(
            delete_data=delete_data))
        self.assertEqual(
            (self.ctx, derived_sc['id']),
            self.rpc_client.delete_software_config.call_args[0])

    def test_handle_delete_none(self):
        self._create_stack(self.template)
        deployment_id = None
        self.deployment.resource_id = deployment_id
        self.assertIsNone(self.deployment.handle_delete()[0])

    def test_check_delete_complete_none(self):
        self._create_stack(self.template)
        delete_data = (None, datetime.datetime.now())
        self.assertTrue(self.deployment.check_delete_complete(
            delete_data=delete_data))

    def test_check_delete_timeout(self):
        # Setup
        self._create_stack(self.template_with_timeout)
        mock_sd = self.mock_deployment()
        mock_sd[rpc_api.SOFTWARE_DEPLOYMENT_ACTION] = 'DELETE'
        mock_sd['server_id'] = 'b509edfb-1448-4b57-8cb1-2e31acccbb8a'
        self.rpc_client.show_software_deployment.return_value = mock_sd

        # Test
        delete_data = (mock_sd,
                       timeutils.utcnow() - datetime.timedelta(seconds=10))
        e = self.assertRaises(exc.Error,
                              self.deployment.check_delete_complete,
                              delete_data)

        # Verify
        self.assertIn('DELETE', e.message)
        self.assertIn('after 5s', e.message)

    def test_check_delete_complete_delete_sd(self):
        # handle_delete will return None if NO_SIGNAL,
        # in this case also need to call the _delete_resource(),
        # otherwise the sd data will residue in db
        self._create_stack(self.template)
        sd = self.mock_deployment()
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        self.rpc_client.show_software_deployment.return_value = sd
        delete_data = (None, datetime.datetime.now())
        self.assertTrue(self.deployment.check_delete_complete(
            delete_data=delete_data))
        self.assertEqual(
            (self.ctx, self.deployment.resource_id),
            self.rpc_client.delete_software_deployment.call_args[0])

    def test_handle_update(self):
        self._create_stack(self.template)

        self.mock_derived_software_config()
        sd = self.mock_deployment()
        rsrc = self.stack['deployment_mysql']

        self.rpc_client.show_software_deployment.return_value = sd
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        config_id = '0ff2e903-78d7-4cca-829e-233af3dae705'
        prop_diff = {
            'config': config_id,
            'name': 'new_name'
        }
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        self.deployment.handle_update(
            json_snippet=snippet, tmpl_diff=None, prop_diff=prop_diff)
        self.assertEqual(
            (self.ctx, config_id),
            self.rpc_client.show_software_config.call_args[0])

        self.assertEqual(
            (self.ctx, self.deployment.resource_id),
            self.rpc_client.show_software_deployment.call_args[0])

        self.assertEqual(
            'new_name',
            self.rpc_client.create_software_config.call_args[1]['name'])

        self.assertEqual({
            'deployment_id': 'c8a19429-7fde-47ea-a42f-40045488226c',
            'action': 'UPDATE',
            'config_id': '9966c8e7-bc9c-42de-aa7d-f2447a952cb2',
            'status': 'IN_PROGRESS',
            'status_reason': u'Deploy data available'},
            self.rpc_client.update_software_deployment.call_args[1])

    def test_handle_suspend_resume(self):
        self._create_stack(self.template_delete_suspend_resume)

        self.mock_software_config()
        derived_sc = self.mock_derived_software_config()
        mock_sd = self.mock_deployment()

        suspend_data = resume_data = (mock_sd, datetime.datetime.now())

        self.rpc_client.show_software_deployment.return_value = mock_sd
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'

        # first, handle the suspend
        self.deployment.handle_suspend()

        self.assertEqual({
            'deployment_id': 'c8a19429-7fde-47ea-a42f-40045488226c',
            'action': 'SUSPEND',
            'config_id': derived_sc['id'],
            'status': 'IN_PROGRESS',
            'status_reason': 'Deploy data available'},
            self.rpc_client.update_software_deployment.call_args[1])

        mock_sd['status'] = 'IN_PROGRESS'
        self.assertFalse(self.deployment.check_suspend_complete(suspend_data))

        mock_sd['status'] = 'COMPLETE'
        self.assertTrue(self.deployment.check_suspend_complete(suspend_data))

        # now, handle the resume
        self.deployment.handle_resume()

        self.assertEqual({
            'deployment_id': 'c8a19429-7fde-47ea-a42f-40045488226c',
            'action': 'RESUME',
            'config_id': derived_sc['id'],
            'status': 'IN_PROGRESS',
            'status_reason': 'Deploy data available'},
            self.rpc_client.update_software_deployment.call_args[1])

        mock_sd['status'] = 'IN_PROGRESS'
        self.assertFalse(self.deployment.check_resume_complete(resume_data))

        mock_sd['status'] = 'COMPLETE'
        self.assertTrue(self.deployment.check_resume_complete(resume_data))

    def test_handle_signal_ok_zero(self):
        self._create_stack(self.template)
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        rpcc = self.rpc_client
        rpcc.signal_software_deployment.return_value = 'deployment succeeded'
        details = {
            'foo': 'bar',
            'deploy_status_code': 0
        }
        ret = self.deployment.handle_signal(details)
        self.assertEqual('deployment succeeded', ret)
        ca = rpcc.signal_software_deployment.call_args[0]
        self.assertEqual(self.ctx, ca[0])
        self.assertEqual('c8a19429-7fde-47ea-a42f-40045488226c', ca[1])
        self.assertEqual({'foo': 'bar', 'deploy_status_code': 0}, ca[2])
        self.assertIsNotNone(ca[3])

    def test_no_signal_action(self):
        self._create_stack(self.template)
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        rpcc = self.rpc_client
        rpcc.signal_software_deployment.return_value = 'deployment succeeded'
        details = {
            'foo': 'bar',
            'deploy_status_code': 0
        }
        actions = [self.deployment.SUSPEND, self.deployment.DELETE]
        ev = self.patchobject(self.deployment, 'handle_signal')
        for action in actions:
            for status in self.deployment.STATUSES:
                self.deployment.state_set(action, status)
                self.deployment.signal(details)
                ev.assert_called_with(details)

    def test_handle_signal_ok_str_zero(self):
        self._create_stack(self.template)
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        rpcc = self.rpc_client
        rpcc.signal_software_deployment.return_value = 'deployment succeeded'
        details = {
            'foo': 'bar',
            'deploy_status_code': '0'
        }
        ret = self.deployment.handle_signal(details)
        self.assertEqual('deployment succeeded', ret)
        ca = rpcc.signal_software_deployment.call_args[0]
        self.assertEqual(self.ctx, ca[0])
        self.assertEqual('c8a19429-7fde-47ea-a42f-40045488226c', ca[1])
        self.assertEqual({'foo': 'bar', 'deploy_status_code': '0'}, ca[2])
        self.assertIsNotNone(ca[3])

    def test_handle_signal_failed(self):
        self._create_stack(self.template)
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        rpcc = self.rpc_client
        rpcc.signal_software_deployment.return_value = 'deployment failed'

        details = {'failed': 'no enough memory found.'}
        ret = self.deployment.handle_signal(details)
        self.assertEqual('deployment failed', ret)
        ca = rpcc.signal_software_deployment.call_args[0]
        self.assertEqual(self.ctx, ca[0])
        self.assertEqual('c8a19429-7fde-47ea-a42f-40045488226c', ca[1])
        self.assertEqual(details, ca[2])
        self.assertIsNotNone(ca[3])

        # Test bug 1332355, where details contains a translateable message
        details = {'failed': _('need more memory.')}
        ret = self.deployment.handle_signal(details)
        self.assertEqual('deployment failed', ret)
        ca = rpcc.signal_software_deployment.call_args[0]
        self.assertEqual(self.ctx, ca[0])
        self.assertEqual('c8a19429-7fde-47ea-a42f-40045488226c', ca[1])
        self.assertEqual(details, ca[2])
        self.assertIsNotNone(ca[3])

    def test_handle_status_code_failed(self):
        self._create_stack(self.template)
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        rpcc = self.rpc_client
        rpcc.signal_software_deployment.return_value = 'deployment failed'

        details = {
            'deploy_stdout': 'A thing happened',
            'deploy_stderr': 'Then it broke',
            'deploy_status_code': -1
        }
        self.deployment.handle_signal(details)
        ca = rpcc.signal_software_deployment.call_args[0]
        self.assertEqual(self.ctx, ca[0])
        self.assertEqual('c8a19429-7fde-47ea-a42f-40045488226c', ca[1])
        self.assertEqual(details, ca[2])
        self.assertIsNotNone(ca[3])

    def test_handle_signal_not_waiting(self):
        self._create_stack(self.template)
        rpcc = self.rpc_client
        rpcc.signal_software_deployment.return_value = None
        details = None
        self.assertIsNone(self.deployment.handle_signal(details))
        ca = rpcc.signal_software_deployment.call_args[0]
        self.assertEqual(self.ctx, ca[0])
        self.assertIsNone(ca[1])
        self.assertIsNone(ca[2])
        self.assertIsNotNone(ca[3])

    def test_fn_get_att(self):
        self._create_stack(self.template)
        sd = {
            'outputs': [
                {'name': 'failed', 'error_output': True},
                {'name': 'foo'}
            ],
            'output_values': {
                'foo': 'bar',
                'deploy_stdout': 'A thing happened',
                'deploy_stderr': 'Extraneous logging',
                'deploy_status_code': 0
            },
            'status': self.deployment.COMPLETE
        }
        self.rpc_client.show_software_deployment.return_value = sd
        self.assertEqual('bar', self.deployment.FnGetAtt('foo'))
        self.assertEqual('A thing happened',
                         self.deployment.FnGetAtt('deploy_stdout'))
        self.assertEqual('Extraneous logging',
                         self.deployment.FnGetAtt('deploy_stderr'))
        self.assertEqual(0, self.deployment.FnGetAtt('deploy_status_code'))

    def test_fn_get_att_convg(self):
        cache_data = {'deployment_mysql': {
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'attrs': {'foo': 'bar'}
        }}
        self._create_stack(self.template, cache_data=cache_data)
        self.assertEqual('bar', self.deployment.FnGetAtt('foo'))

    def test_fn_get_att_error(self):
        self._create_stack(self.template)

        sd = {
            'outputs': [],
            'output_values': {'foo': 'bar'},
        }
        self.rpc_client.show_software_deployment.return_value = sd

        err = self.assertRaises(
            exc.InvalidTemplateAttribute,
            self.deployment.FnGetAtt, 'foo2')
        self.assertEqual(
            'The Referenced Attribute (deployment_mysql foo2) is incorrect.',
            six.text_type(err))

    def test_handle_action(self):
        self._create_stack(self.template)

        self.mock_software_config()
        sd = self.mock_deployment()
        rsrc = self.stack['deployment_mysql']

        self.rpc_client.show_software_deployment.return_value = sd
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        config_id = '0ff2e903-78d7-4cca-829e-233af3dae705'
        prop_diff = {'config': config_id}
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        # by default (no 'actions' property) SoftwareDeployment must only
        # trigger for CREATE and UPDATE
        self.assertIsNotNone(self.deployment.handle_create())
        self.assertIsNotNone(self.deployment.handle_update(
            json_snippet=snippet, tmpl_diff=None, prop_diff=prop_diff))
        # ... but it must not trigger for SUSPEND, RESUME and DELETE
        self.assertIsNone(self.deployment.handle_suspend()[0])
        self.assertIsNone(self.deployment.handle_resume()[0])
        self.assertIsNone(self.deployment.handle_delete()[0])

    def test_handle_action_for_component(self):
        self._create_stack(self.template)

        self.mock_software_component()
        sd = self.mock_deployment()
        rsrc = self.stack['deployment_mysql']

        self.rpc_client.show_software_deployment.return_value = sd
        self.deployment.resource_id = 'c8a19429-7fde-47ea-a42f-40045488226c'
        config_id = '0ff2e903-78d7-4cca-829e-233af3dae705'
        prop_diff = {'config': config_id}
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(), props)

        # for a SoftwareComponent, SoftwareDeployment must always trigger
        self.assertIsNotNone(self.deployment.handle_create())
        self.assertIsNotNone(self.deployment.handle_update(
            json_snippet=snippet, tmpl_diff=None, prop_diff=prop_diff))
        self.assertIsNotNone(self.deployment.handle_suspend())
        self.assertIsNotNone(self.deployment.handle_resume())
        self.assertIsNotNone(self.deployment.handle_delete())

    def test_handle_unused_action_for_component(self):
        self._create_stack(self.template)

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
        self.rpc_client.show_software_config.return_value = config
        sd = self.mock_deployment()

        self.rpc_client.show_software_deployment.return_value = sd

        self.assertIsNotNone(self.deployment.handle_create())
        self.assertIsNone(self.deployment.handle_delete()[0])

    def test_get_temp_url(self):
        dep_data = {}

        sc = mock.MagicMock()
        scc = self.patch(
            'heat.engine.clients.os.swift.SwiftClientPlugin._create')
        scc.return_value = sc
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.1/v1/AUTH_test_tenant_id'

        self._create_stack(self.template_temp_url_signal)

        def data_set(key, value, redact=False):
            dep_data[key] = value

        self.deployment.data_set = data_set
        self.deployment.data = mock.Mock(
            return_value=dep_data)

        self.deployment.id = 23
        self.deployment.uuid = str(uuid.uuid4())
        self.deployment.action = self.deployment.CREATE
        object_name = self.deployment.physical_resource_name()

        temp_url = self.deployment._get_swift_signal_url()
        temp_url_pattern = re.compile(
            '^http://192.0.2.1/v1/AUTH_test_tenant_id/'
            '(.*)/(software_deployment_test_stack-deployment_mysql-.*)'
            '\\?temp_url_sig=.*&temp_url_expires=\\d*$')
        self.assertRegex(temp_url, temp_url_pattern)
        m = temp_url_pattern.search(temp_url)
        container = m.group(1)
        self.assertEqual(object_name, m.group(2))
        self.assertEqual(dep_data['swift_signal_object_name'], object_name)

        self.assertEqual(dep_data['swift_signal_url'], temp_url)

        self.assertEqual(temp_url, self.deployment._get_swift_signal_url())

        sc.put_container.assert_called_once_with(container)
        sc.put_object.assert_called_once_with(container, object_name, '')

    def test_delete_temp_url(self):
        object_name = str(uuid.uuid4())
        dep_data = {
            'swift_signal_object_name': object_name
        }
        self._create_stack(self.template_temp_url_signal)

        self.deployment.data_delete = mock.MagicMock()
        self.deployment.data = mock.Mock(
            return_value=dep_data)

        sc = mock.MagicMock()
        sc.get_container.return_value = ({}, [{'name': object_name}])
        sc.head_container.return_value = {
            'x-container-object-count': 0
        }
        scc = self.patch(
            'heat.engine.clients.os.swift.SwiftClientPlugin._create')
        scc.return_value = sc

        self.deployment.id = 23
        self.deployment.uuid = str(uuid.uuid4())
        container = self.stack.id
        self.deployment._delete_swift_signal_url()
        sc.delete_object.assert_called_once_with(container, object_name)
        self.assertEqual(
            [mock.call('swift_signal_object_name'),
             mock.call('swift_signal_url')],
            self.deployment.data_delete.mock_calls)

        swift_exc = swift.SwiftClientPlugin.exceptions_module
        sc.delete_object.side_effect = swift_exc.ClientException(
            'Not found', http_status=404)
        self.deployment._delete_swift_signal_url()
        self.assertEqual(
            [mock.call('swift_signal_object_name'),
             mock.call('swift_signal_url'),
             mock.call('swift_signal_object_name'),
             mock.call('swift_signal_url')],
            self.deployment.data_delete.mock_calls)

        del(dep_data['swift_signal_object_name'])
        self.deployment.physical_resource_name = mock.Mock()
        self.deployment._delete_swift_signal_url()
        self.assertFalse(self.deployment.physical_resource_name.called)

    def test_handle_action_temp_url(self):

        self._create_stack(self.template_temp_url_signal)
        dep_data = {
            'swift_signal_url': (
                'http://192.0.2.1/v1/AUTH_a/b/c'
                '?temp_url_sig=ctemp_url_expires=1234')
        }
        self.deployment.data = mock.Mock(
            return_value=dep_data)

        self.mock_software_config()

        for action in ('DELETE', 'SUSPEND', 'RESUME'):
            self.assertIsNone(self.deployment._handle_action(action))
        for action in ('CREATE', 'UPDATE'):
            self.assertIsNotNone(self.deployment._handle_action(action))

    def test_get_zaqar_queue(self):
        dep_data = {}

        self._create_stack(self.template_zaqar_signal)

        def data_set(key, value, redact=False):
            dep_data[key] = value

        self.deployment.data_set = data_set
        self.deployment.data = mock.Mock(return_value=dep_data)

        self.deployment.id = 23
        self.deployment.uuid = str(uuid.uuid4())
        self.deployment.action = self.deployment.CREATE

        queue_id = self.deployment._get_zaqar_signal_queue_id()
        self.assertEqual(queue_id, dep_data['zaqar_signal_queue_id'])

        self.assertEqual(queue_id,
                         self.deployment._get_zaqar_signal_queue_id())

    @mock.patch.object(zaqar.ZaqarClientPlugin, 'create_for_tenant')
    def test_delete_zaqar_queue(self, zcc):
        queue_id = str(uuid.uuid4())
        dep_data = {
            'password': 'password',
            'zaqar_signal_queue_id': queue_id
        }
        self._create_stack(self.template_zaqar_signal)

        self.deployment.data_delete = mock.MagicMock()
        self.deployment.data = mock.Mock(return_value=dep_data)

        zc = mock.MagicMock()
        zcc.return_value = zc

        self.deployment.id = 23
        self.deployment.uuid = str(uuid.uuid4())
        self.deployment._delete_zaqar_signal_queue()
        zc.queue.assert_called_once_with(queue_id)
        self.assertTrue(zc.queue(self.deployment.uuid).delete.called)
        self.assertEqual(
            [mock.call('zaqar_signal_queue_id')],
            self.deployment.data_delete.mock_calls)

        zaqar_exc = zaqar.ZaqarClientPlugin.exceptions_module
        zc.queue.delete.side_effect = zaqar_exc.ResourceNotFound()
        self.deployment._delete_zaqar_signal_queue()
        self.assertEqual(
            [mock.call('zaqar_signal_queue_id'),
             mock.call('zaqar_signal_queue_id')],
            self.deployment.data_delete.mock_calls)

        dep_data.pop('zaqar_signal_queue_id')
        self.deployment.physical_resource_name = mock.Mock()
        self.deployment._delete_zaqar_signal_queue()
        self.assertEqual(2, len(self.deployment.data_delete.mock_calls))

    def test_server_exists(self):
        # Setup
        self._create_stack(self.template_delete_suspend_resume)
        mock_sd = {'server_id': 'b509edfb-1448-4b57-8cb1-2e31acccbb8a'}

        # For a success case, this doesn't raise an exception
        self.patchobject(nova.NovaClientPlugin, 'get_server')

        # Test
        result = self.deployment._server_exists(mock_sd)
        self.assertTrue(result)

    def test_server_exists_no_server(self):
        # Setup
        self._create_stack(self.template_delete_suspend_resume)
        mock_sd = {'server_id': 'b509edfb-1448-4b57-8cb1-2e31acccbb8a'}

        # For a success case, this doesn't raise an exception
        self.patchobject(nova.NovaClientPlugin, 'get_server',
                         side_effect=exc.EntityNotFound)

        # Test
        result = self.deployment._server_exists(mock_sd)
        self.assertFalse(result)


class SoftwareDeploymentGroupTest(common.HeatTestCase):

    template = {
        'heat_template_version': '2013-05-23',
        'resources': {
            'deploy_mysql': {
                'type': 'OS::Heat::SoftwareDeploymentGroup',
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
        common.HeatTestCase.setUp(self)
        self.rpc_client = mock.MagicMock()

    def test_build_resource_definition(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeploymentGroup('test', snip, stack)

        expect = rsrc_defn.ResourceDefinition(
            None,
            "OS::Heat::SoftwareDeployment",
            {'actions': ['CREATE', 'UPDATE'],
                'config': 'config_uuid',
                'input_values': {'foo': 'bar'},
                'name': '10_config',
                'server': 'uuid1',
                'signal_transport': 'CFN_SIGNAL'})

        rdef = resg.get_resource_def()
        self.assertEqual(
            expect, resg.build_resource_definition('server1', rdef))
        rdef = resg.get_resource_def(include_all=True)
        self.assertEqual(
            expect, resg.build_resource_definition('server1', rdef))

    def test_resource_names(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeploymentGroup('test', snip, stack)
        self.assertEqual(
            set(('server1', 'server2')),
            set(resg._resource_names())
        )

        resg.properties = {'servers': {'s1': 'u1', 's2': 'u2', 's3': 'u3'}}
        self.assertEqual(
            set(('s1', 's2', 's3')),
            set(resg._resource_names()))

    def test_assemble_nested(self):
        """Tests nested stack implements group creation based on properties.

        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeploymentGroup('test', snip, stack)
        templ = {
            "heat_template_version": "2015-04-30",
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

        self.assertEqual(templ, resg._assemble_nested(['server1',
                                                       'server2']).t)

    def test_attributes(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeploymentGroup('test', snip, stack)
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

        server2.FnGetAtt.assert_has_calls([
            mock.call('deploy_stdout'),
            mock.call('deploy_stderr'),
            mock.call('deploy_status_code'),
        ])

    def test_attributes_path(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeploymentGroup('test', snip, stack)
        nested = self.patchobject(resg, 'nested')
        server1 = mock.MagicMock()
        server2 = mock.MagicMock()
        nested.return_value = {
            'server1': server1,
            'server2': server2
        }

        server1.FnGetAtt.return_value = 'Thing happened on server1'
        server2.FnGetAtt.return_value = 'ouch'
        self.assertEqual('Thing happened on server1',
                         resg.FnGetAtt('deploy_stdouts', 'server1'))
        self.assertEqual('ouch',
                         resg.FnGetAtt('deploy_stdouts', 'server2'))

        server1.FnGetAtt.return_value = ''
        server2.FnGetAtt.return_value = 'Its gone Pete Tong'
        self.assertEqual('', resg.FnGetAtt('deploy_stderrs', 'server1'))
        self.assertEqual('Its gone Pete Tong',
                         resg.FnGetAtt('deploy_stderrs', 'server2'))

        server1.FnGetAtt.return_value = 0
        server2.FnGetAtt.return_value = 1
        self.assertEqual(0, resg.FnGetAtt('deploy_status_codes', 'server1'))
        self.assertEqual(1, resg.FnGetAtt('deploy_status_codes', 'server2'))

        server1.FnGetAtt.assert_has_calls([
            mock.call('deploy_stdout'),
            mock.call('deploy_stdout'),
            mock.call('deploy_stderr'),
            mock.call('deploy_stderr'),
            mock.call('deploy_status_code'),
            mock.call('deploy_status_code'),
        ])

        server2.FnGetAtt.assert_has_calls([
            mock.call('deploy_stdout'),
            mock.call('deploy_stdout'),
            mock.call('deploy_stderr'),
            mock.call('deploy_stderr'),
            mock.call('deploy_status_code'),
            mock.call('deploy_status_code'),
        ])

    def test_attributes_passthrough_key(self):
        '''Prove attributes not in the schema pass-through.'''
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeploymentGroup('test', snip, stack)
        nested = self.patchobject(resg, 'nested')
        server1 = mock.MagicMock()
        server2 = mock.MagicMock()
        nested.return_value = {
            'server1': server1,
            'server2': server2
        }

        server1.FnGetAtt.return_value = 'attr1'
        server2.FnGetAtt.return_value = 'attr2'
        self.assertEqual({
            'server1': 'attr1',
            'server2': 'attr2'
        }, resg.FnGetAtt('some_attr'))

        server1.FnGetAtt.assert_has_calls([
            mock.call('some_attr'),
        ])

        server2.FnGetAtt.assert_has_calls([
            mock.call('some_attr'),
        ])

    def test_validate(self):
        stack = utils.parse_stack(self.template)
        snip = stack.t.resource_definitions(stack)['deploy_mysql']
        resg = sd.SoftwareDeploymentGroup('deploy_mysql', snip, stack)
        self.assertIsNone(resg.validate())
