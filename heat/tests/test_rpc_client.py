#
# Copyright 2012, Red Hat, Inc.
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

"""
Unit Tests for heat.rpc.client
"""

import copy

import mock
from oslo_messaging._drivers import common as rpc_common
from oslo_utils import reflection

from heat.common import exception
from heat.common import identifier
from heat.rpc import client as rpc_client
from heat.tests import common
from heat.tests import utils


class EngineRpcAPITestCase(common.HeatTestCase):

    def setUp(self):
        super(EngineRpcAPITestCase, self).setUp()
        self.identity = dict(identifier.HeatIdentifier('engine_test_tenant',
                                                       '6',
                                                       'wordpress'))
        self.rpcapi = rpc_client.EngineClient()

    def _to_remote_error(self, error):
        """Converts the given exception to the one with the _Remote suffix."""
        exc_info = (type(error), error, None)
        serialized = rpc_common.serialize_remote_exception(exc_info)
        remote_error = rpc_common.deserialize_remote_exception(
            serialized, ["heat.common.exception"])
        return remote_error

    def test_local_error_name(self):
        ex = exception.NotFound()
        self.assertEqual('NotFound', self.rpcapi.local_error_name(ex))

        exr = self._to_remote_error(ex)
        self.assertEqual('NotFound_Remote',
                         reflection.get_class_name(exr, fully_qualified=False))
        self.assertEqual('NotFound', self.rpcapi.local_error_name(exr))

    def test_ignore_error_by_name(self):
        ex = exception.NotFound()
        exr = self._to_remote_error(ex)

        filter_exc = self.rpcapi.ignore_error_by_name('NotFound')

        with filter_exc:
            raise ex
        with filter_exc:
            raise exr

        def should_raise(exc):
            with self.rpcapi.ignore_error_by_name('NotSupported'):
                raise exc

        self.assertRaises(exception.NotFound, should_raise, ex)
        self.assertRaises(exception.NotFound, should_raise, exr)

    def test_ignore_error_named(self):
        ex = exception.NotFound()
        exr = self._to_remote_error(ex)

        self.rpcapi.ignore_error_named(ex, 'NotFound')
        self.rpcapi.ignore_error_named(exr, 'NotFound')
        self.assertRaises(
            exception.NotFound,
            self.rpcapi.ignore_error_named,
            ex,
            'NotSupported')
        self.assertRaises(
            exception.NotFound,
            self.rpcapi.ignore_error_named,
            exr,
            'NotSupported')

    def _test_engine_api(self, method, rpc_method, **kwargs):
        ctxt = utils.dummy_context()
        expected_retval = 'foo' if method == 'call' else None

        kwargs.pop('version', None)
        if 'expected_message' in kwargs:
            expected_message = kwargs['expected_message']
            del kwargs['expected_message']
        else:
            expected_message = self.rpcapi.make_msg(method, **kwargs)

        cast_and_call = ['delete_stack']
        if method in cast_and_call:
            kwargs['cast'] = rpc_method != 'call'

        with mock.patch.object(self.rpcapi, rpc_method) as mock_rpc_method:
            mock_rpc_method.return_value = expected_retval

            retval = getattr(self.rpcapi, method)(ctxt, **kwargs)

            self.assertEqual(expected_retval, retval)
            expected_args = [ctxt, expected_message, mock.ANY]
            actual_args, _ = mock_rpc_method.call_args
            for expected_arg, actual_arg in zip(expected_args,
                                                actual_args):
                self.assertEqual(expected_arg, actual_arg)

    def test_authenticated_to_backend(self):
        self._test_engine_api('authenticated_to_backend', 'call')

    def test_list_stacks(self):
        default_args = {
            'limit': mock.ANY,
            'sort_keys': mock.ANY,
            'marker': mock.ANY,
            'sort_dir': mock.ANY,
            'filters': mock.ANY,
            'show_deleted': mock.ANY,
            'show_nested': mock.ANY,
            'show_hidden': mock.ANY,
            'tags': mock.ANY,
            'tags_any': mock.ANY,
            'not_tags': mock.ANY,
            'not_tags_any': mock.ANY,
        }
        self._test_engine_api('list_stacks', 'call', **default_args)

    def test_count_stacks(self):
        default_args = {
            'filters': mock.ANY,
            'show_deleted': mock.ANY,
            'show_nested': mock.ANY,
            'show_hidden': mock.ANY,
            'tags': mock.ANY,
            'tags_any': mock.ANY,
            'not_tags': mock.ANY,
            'not_tags_any': mock.ANY,
        }
        self._test_engine_api('count_stacks', 'call', **default_args)

    def test_identify_stack(self):
        self._test_engine_api('identify_stack', 'call',
                              stack_name='wordpress')

    def test_show_stack(self):
        self._test_engine_api('show_stack', 'call', stack_identity='wordpress',
                              resolve_outputs=True)

    def test_preview_stack(self):
        self._test_engine_api('preview_stack', 'call', stack_name='wordpress',
                              template={u'Foo': u'bar'},
                              params={u'InstanceType': u'm1.xlarge'},
                              files={u'a_file': u'the contents'},
                              environment_files=['foo.yaml'],
                              files_container=None,
                              args={'timeout_mins': u'30'})

    def test_create_stack(self):
        kwargs = dict(stack_name='wordpress',
                      template={u'Foo': u'bar'},
                      params={u'InstanceType': u'm1.xlarge'},
                      files={u'a_file': u'the contents'},
                      environment_files=['foo.yaml'],
                      files_container=None,
                      args={'timeout_mins': u'30'})
        call_kwargs = copy.deepcopy(kwargs)
        call_kwargs['owner_id'] = None
        call_kwargs['nested_depth'] = 0
        call_kwargs['user_creds_id'] = None
        call_kwargs['stack_user_project_id'] = None
        call_kwargs['parent_resource_name'] = None
        call_kwargs['template_id'] = None
        expected_message = self.rpcapi.make_msg('create_stack', **call_kwargs)
        kwargs['expected_message'] = expected_message
        self._test_engine_api('create_stack', 'call', **kwargs)

    def test_update_stack(self):
        kwargs = dict(stack_identity=self.identity,
                      template={u'Foo': u'bar'},
                      params={u'InstanceType': u'm1.xlarge'},
                      files={},
                      environment_files=['foo.yaml'],
                      files_container=None,
                      args=mock.ANY)
        call_kwargs = copy.deepcopy(kwargs)
        call_kwargs['template_id'] = None
        expected_message = self.rpcapi.make_msg('update_stack', **call_kwargs)
        self._test_engine_api('update_stack', 'call',
                              expected_message=expected_message,
                              **kwargs)

    def test_preview_update_stack(self):
        self._test_engine_api('preview_update_stack', 'call',
                              stack_identity=self.identity,
                              template={u'Foo': u'bar'},
                              params={u'InstanceType': u'm1.xlarge'},
                              files={},
                              environment_files=['foo.yaml'],
                              files_container=None,
                              args=mock.ANY)

    def test_get_template(self):
        self._test_engine_api('get_template', 'call',
                              stack_identity=self.identity)

    def test_delete_stack_cast(self):
        self._test_engine_api('delete_stack', 'cast',
                              stack_identity=self.identity)

    def test_delete_stack_call(self):
        self._test_engine_api('delete_stack', 'call',
                              stack_identity=self.identity)

    def test_validate_template(self):
        self._test_engine_api('validate_template', 'call',
                              template={u'Foo': u'bar'},
                              params={u'Egg': u'spam'},
                              files=None,
                              environment_files=['foo.yaml'],
                              files_container=None,
                              ignorable_errors=None,
                              show_nested=False,
                              version='1.24')

    def test_list_resource_types(self):
        self._test_engine_api('list_resource_types',
                              'call',
                              support_status=None,
                              type_name=None,
                              heat_version=None,
                              with_description=False,
                              version='1.30')

    def test_resource_schema(self):
        self._test_engine_api('resource_schema', 'call', type_name="TYPE",
                              with_description=False, version='1.30')

    def test_generate_template(self):
        self._test_engine_api('generate_template', 'call',
                              type_name="TYPE", template_type='cfn')

    def test_list_events(self):
        kwargs = {'stack_identity': self.identity,
                  'limit': None,
                  'marker': None,
                  'sort_keys': None,
                  'sort_dir': None,
                  'filters': None,
                  'nested_depth': None}
        self._test_engine_api('list_events', 'call', **kwargs)

    def test_describe_stack_resource(self):
        self._test_engine_api('describe_stack_resource', 'call',
                              stack_identity=self.identity,
                              resource_name='LogicalResourceId',
                              with_attr=None)

    def test_find_physical_resource(self):
        self._test_engine_api('find_physical_resource', 'call',
                              physical_resource_id=u'404d-a85b-5315293e67de')

    def test_describe_stack_resources(self):
        self._test_engine_api('describe_stack_resources', 'call',
                              stack_identity=self.identity,
                              resource_name=u'WikiDatabase')

    def test_list_stack_resources(self):
        self._test_engine_api('list_stack_resources', 'call',
                              stack_identity=self.identity,
                              nested_depth=0,
                              with_detail=False,
                              filters=None,
                              version=1.25)

    def test_stack_suspend(self):
        self._test_engine_api('stack_suspend', 'call',
                              stack_identity=self.identity)

    def test_stack_resume(self):
        self._test_engine_api('stack_resume', 'call',
                              stack_identity=self.identity)

    def test_stack_cancel_update(self):
        self._test_engine_api('stack_cancel_update', 'call',
                              stack_identity=self.identity,
                              cancel_with_rollback=False,
                              version='1.14')

    def test_resource_signal(self):
        self._test_engine_api('resource_signal', 'call',
                              stack_identity=self.identity,
                              resource_name='LogicalResourceId',
                              details={u'wordpress': []},
                              sync_call=True)

    def test_list_software_configs(self):
        self._test_engine_api('list_software_configs', 'call',
                              limit=mock.ANY, marker=mock.ANY)

    def test_show_software_config(self):
        self._test_engine_api('show_software_config', 'call',
                              config_id='cda89008-6ea6-4057-b83d-ccde8f0b48c9')

    def test_create_software_config(self):
        self._test_engine_api('create_software_config', 'call',
                              group='Heat::Shell',
                              name='config_mysql',
                              config='#!/bin/bash',
                              inputs=[],
                              outputs=[],
                              options={})

    def test_delete_software_config(self):
        self._test_engine_api('delete_software_config', 'call',
                              config_id='cda89008-6ea6-4057-b83d-ccde8f0b48c9')

    def test_list_software_deployments(self):
        self._test_engine_api('list_software_deployments', 'call',
                              server_id=None)
        self._test_engine_api('list_software_deployments', 'call',
                              server_id='9dc13236-d342-451f-a885-1c82420ba5ed')

    def test_show_software_deployment(self):
        deployment_id = '86729f02-4648-44d8-af44-d0ec65b6abc9'
        self._test_engine_api('show_software_deployment', 'call',
                              deployment_id=deployment_id)

    def test_check_software_deployment(self):
        deployment_id = '86729f02-4648-44d8-af44-d0ec65b6abc9'
        self._test_engine_api('check_software_deployment', 'call',
                              deployment_id=deployment_id, timeout=100)

    def test_create_software_deployment(self):
        self._test_engine_api(
            'create_software_deployment', 'call',
            server_id='9f1f0e00-05d2-4ca5-8602-95021f19c9d0',
            config_id='48e8ade1-9196-42d5-89a2-f709fde42632',
            deployment_id='86729f02-4648-44d8-af44-d0ec65b6abc9',
            stack_user_project_id='65728b74-cfe7-4f17-9c15-11d4f686e591',
            input_values={},
            action='INIT',
            status='COMPLETE',
            status_reason=None)

    def test_update_software_deployment(self):
        deployment_id = '86729f02-4648-44d8-af44-d0ec65b6abc9'
        self._test_engine_api('update_software_deployment', 'call',
                              deployment_id=deployment_id,
                              config_id='48e8ade1-9196-42d5-89a2-f709fde42632',
                              input_values={},
                              output_values={},
                              action='DEPLOYED',
                              status='COMPLETE',
                              status_reason=None,
                              updated_at=None)

    def test_delete_software_deployment(self):
        deployment_id = '86729f02-4648-44d8-af44-d0ec65b6abc9'
        self._test_engine_api('delete_software_deployment', 'call',
                              deployment_id=deployment_id)

    def test_show_snapshot(self):
        snapshot_id = '86729f02-4648-44d8-af44-d0ec65b6abc9'
        self._test_engine_api('show_snapshot', 'call',
                              stack_identity=self.identity,
                              snapshot_id=snapshot_id)

    def test_stack_snapshot(self):
        self._test_engine_api(
            'stack_snapshot', 'call', stack_identity=self.identity,
            name='snap1')

    def test_delete_snapshot(self):
        snapshot_id = '86729f02-4648-44d8-af44-d0ec65b6abc9'
        self._test_engine_api('delete_snapshot', 'call',
                              stack_identity=self.identity,
                              snapshot_id=snapshot_id)

    def test_list_services(self):
        self._test_engine_api('list_services', 'call', version='1.4')

    def test_stack_list_outputs(self):
        self._test_engine_api(
            'list_outputs', 'call', stack_identity=self.identity,
            version='1.19'
        )

    def test_stack_show_output(self):
        self._test_engine_api(
            'show_output', 'call', stack_identity=self.identity,
            output_key='test', version='1.19')

    def test_export_stack(self):
        self._test_engine_api('export_stack',
                              'call',
                              stack_identity=self.identity,
                              version='1.22')

    def test_resource_mark_unhealthy(self):
        self._test_engine_api('resource_mark_unhealthy', 'call',
                              stack_identity=self.identity,
                              resource_name='LogicalResourceId',
                              mark_unhealthy=True,
                              resource_status_reason="Any reason",
                              version='1.26')

    def test_get_environment(self):
        self._test_engine_api(
            'get_environment', 'call', stack_identity=self.identity,
            version='1.28')

    def test_get_files(self):
        self._test_engine_api(
            'get_files', 'call', stack_identity=self.identity,
            version='1.32')
