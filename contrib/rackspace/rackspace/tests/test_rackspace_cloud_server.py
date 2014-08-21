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
import mox
from oslo.config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import template
from heat.openstack.common import uuidutils
from heat.tests import common
from heat.tests import utils
from heat.tests.v1_1 import fakes

from ..resources import cloud_server  # noqa


wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "key_name" : {
      "Description" : "key_name",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "Rackspace::Cloud::Server",
      "Properties": {
        "image" : "CentOS 5.2",
        "flavor"   : "256 MB Server",
        "key_name"   : "test",
        "user_data"       : "wordpress"
      }
    }
  }
}
'''

cfg.CONF.import_opt('region_name_for_services', 'heat.common.config')


class CloudServersTest(common.HeatTestCase):
    def setUp(self):
        super(CloudServersTest, self).setUp()
        cfg.CONF.set_override('region_name_for_services', 'RegionOne')
        self.ctx = utils.dummy_context()

        self.fc = fakes.FakeClient()
        mock_nova_create = mock.Mock()
        self.ctx.clients.client_plugin(
            'nova')._create = mock_nova_create
        mock_nova_create.return_value = self.fc

        self.stub_keystoneclient()
        # Test environment may not have pyrax client library installed and if
        # pyrax is not installed resource class would not be registered.
        # So register resource provider class explicitly for unit testing.
        resource._register_class("Rackspace::Cloud::Server",
                                 cloud_server.CloudServer)

    def _mock_get_image_id_success(self, imageId):
        self.mock_get_image = mock.Mock()
        self.ctx.clients.client_plugin(
            'glance').get_image_id = self.mock_get_image
        self.mock_get_image.return_value = imageId

    def _stub_server_validate(self, server, imageId_input, image_id):
        # stub glance image validate
        self._mock_get_image_id_success(image_id)

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        templ = template.Template(t)
        stack = parser.Stack(self.ctx, stack_name, templ,
                             environment.Environment({'key_name': 'test'}),
                             stack_id=uuidutils.generate_uuid())
        return (templ, stack)

    def _setup_test_server(self, return_server, name, image_id=None,
                           override_name=False, stub_create=True, exit_code=0):
        stack_name = '%s_s' % name
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties']['image'] = \
            image_id or 'CentOS 5.2'
        tmpl.t['Resources']['WebServer']['Properties']['flavor'] = \
            '256 MB Server'

        server_name = '%s' % name
        if override_name:
            tmpl.t['Resources']['WebServer']['Properties']['name'] = \
                server_name

        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer(server_name,
                                          resource_defns['WebServer'],
                                          stack)

        self._stub_server_validate(server, image_id or 'CentOS 5.2', 1)
        if stub_create:
            self.m.StubOutWithMock(self.fc.servers, 'create')
            self.fc.servers.create(
                image=1,
                flavor=1,
                key_name='test',
                name=override_name and server.name or utils.PhysName(
                    stack_name, server.name),
                security_groups=[],
                userdata=mox.IgnoreArg(),
                scheduler_hints=None,
                meta=None,
                nics=None,
                availability_zone=None,
                block_device_mapping=None,
                config_drive=True,
                disk_config=None,
                reservation_id=None,
                files=mox.IgnoreArg(),
                admin_pass=None).AndReturn(return_server)

        return server

    def _create_test_server(self, return_server, name, override_name=False,
                            stub_create=True, exit_code=0):
        server = self._setup_test_server(return_server, name,
                                         stub_create=stub_create,
                                         exit_code=exit_code)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        return server

    def _mock_metadata_os_distro(self):
        image_data = mock.Mock(metadata={'os_distro': 'centos'})
        self.fc.images.get = mock.Mock(return_value=image_data)

    def test_rackconnect_deployed(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rackconnect_automation_status': 'DEPLOYED'}
        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_deployed')
        server.context.roles = ['rack_connect']
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.assertEqual('CREATE', server.action)
        self.assertEqual('COMPLETE', server.status)
        self.m.VerifyAll()

    def test_rackconnect_failed(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rackconnect_automation_status': 'FAILED'}
        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_failed')
        server.context.roles = ['rack_connect']
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: RackConnect automation FAILED',
                         six.text_type(exc))

    def test_rackconnect_unprocessable(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rackconnect_automation_status':
                                  'UNPROCESSABLE',
                                  'rackconnect_unprocessable_reason':
                                  'Fake reason'}
        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_unprocessable')
        server.context.roles = ['rack_connect']
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.assertEqual('CREATE', server.action)
        self.assertEqual('COMPLETE', server.status)
        self.m.VerifyAll()

    def test_rackconnect_unknown(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rackconnect_automation_status': 'FOO'}
        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_unknown')
        server.context.roles = ['rack_connect']
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: Unknown RackConnect automation status: FOO',
                         six.text_type(exc))

    def test_rackconnect_deploying(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'srv_sts_bld')
        server.resource_id = 1234
        server.context.roles = ['rack_connect']

        check_iterations = [0]

        # Bind fake get method which check_create_complete will call
        def activate_status(server):
            check_iterations[0] += 1
            if check_iterations[0] == 1:
                server.metadata['rackconnect_automation_status'] = 'DEPLOYING'
            if check_iterations[0] == 2:
                server.status = 'ACTIVE'
            if check_iterations[0] > 3:
                server.metadata['rackconnect_automation_status'] = 'DEPLOYED'
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_rackconnect_no_status(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'srv_sts_bld')
        server.resource_id = 1234
        server.context.roles = ['rack_connect']

        check_iterations = [0]

        # Bind fake get method which check_create_complete will call
        def activate_status(server):
            check_iterations[0] += 1
            if check_iterations[0] == 1:
                server.status = 'ACTIVE'
            if check_iterations[0] == 2:
                server.metadata = {}
            if check_iterations[0] > 2:
                server.metadata['rackconnect_automation_status'] = 'DEPLOYED'
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_managed_cloud_lifecycle(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'srv_sts_bld')
        server.resource_id = 1234
        server.context.roles = ['rack_connect', 'rax_managed']

        check_iterations = [0]

        # Bind fake get method which check_create_complete will call
        def activate_status(server):
            check_iterations[0] += 1
            if check_iterations[0] == 1:
                server.status = 'ACTIVE'
            if check_iterations[0] == 2:
                server.metadata = {'rackconnect_automation_status': 'DEPLOYED'}
            if check_iterations[0] == 3:
                server.metadata = {
                    'rackconnect_automation_status': 'DEPLOYED',
                    'rax_service_level_automation': 'In Progress'}
            if check_iterations[0] > 3:
                server.metadata = {
                    'rackconnect_automation_status': 'DEPLOYED',
                    'rax_service_level_automation': 'Complete'}
        return_server.get = activate_status.__get__(return_server)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_managed_cloud_build_error(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation':
                                  'Build Error'}
        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        server = self._setup_test_server(return_server,
                                         'test_managed_cloud_build_error')
        server.context.roles = ['rax_managed']
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: Managed Cloud automation failed',
                         six.text_type(exc))

    def test_managed_cloud_unknown(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation': 'FOO'}
        self.m.StubOutWithMock(return_server, 'get')
        return_server.get()
        server = self._setup_test_server(return_server,
                                         'test_managed_cloud_unknown')
        server.context.roles = ['rax_managed']
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: Unknown Managed Cloud automation status: FOO',
                         six.text_type(exc))

    @mock.patch.object(resource.Resource, 'data_set')
    def test_create_store_admin_pass_resource_data(self,
                                                   mock_data_set):
        self._mock_metadata_os_distro()
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'autogenerated'
        stack_name = 'admin_pass_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t.t['Resources']['WebServer']['Properties']['save_admin_pass'] = True
        resource_defns = t.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)

        self.fc.servers.create = mock.Mock(return_value=return_server)
        self._mock_get_image_id_success('image_id')
        scheduler.TaskRunner(server.create)()
        expected_call = mock.call(server.ADMIN_PASS,
                                  'autogenerated', redact=True)
        self.assertIn(expected_call, mock_data_set.call_args_list)

    @mock.patch.object(resource.Resource, 'data_set')
    def test_create_save_admin_pass_is_false(self, mock_data_set):
        self._mock_metadata_os_distro()
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'autogenerated'
        stack_name = 'admin_pass_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t.t['Resources']['WebServer']['Properties']['save_admin_pass'] = False
        resource_defns = t.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)

        self.fc.servers.create = mock.Mock(return_value=return_server)
        self._mock_get_image_id_success('image_id')
        scheduler.TaskRunner(server.create)()
        expected_call = mock.call(mock.ANY, server.ADMIN_PASS,
                                  mock.ANY, mock.ANY)
        self.assertNotIn(expected_call, mock_data_set.call_args_list)

    @mock.patch.object(resource.Resource, 'data_set')
    def test_create_save_admin_pass_defaults_to_false(self,
                                                      mock_data_set):
        self._mock_metadata_os_distro()
        return_server = self.fc.servers.list()[1]
        return_server.adminPass = 'autogenerated'
        stack_name = 'admin_pass_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t.t['Resources']['WebServer']['Properties']['save_admin_pass'] = None
        resource_defns = t.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)

        self.fc.servers.create = mock.Mock(return_value=return_server)
        self._mock_get_image_id_success('image_id')

        scheduler.TaskRunner(server.create)()
        expected_call = mock.call(mock.ANY, server.ADMIN_PASS,
                                  mock.ANY, mock.ANY)
        self.assertNotIn(expected_call, mock_data_set.call_args_list)

    @mock.patch.object(resource.Resource, 'data_set')
    def test_create_without_adminPass_attribute(self,
                                                mock_data_set):
        self._mock_metadata_os_distro()
        return_server = self.fc.servers.list()[1]
        stack_name = 'admin_pass_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)

        self.fc.servers.create = mock.Mock(return_value=return_server)
        self._mock_get_image_id_success('image_id')

        scheduler.TaskRunner(server.create)()
        expected_call = mock.call(mock.ANY, server.ADMIN_PASS,
                                  mock.ANY, redact=mock.ANY)
        self.assertNotIn(expected_call, mock_data_set.call_args_list)

    @mock.patch.object(resource.Resource, 'data')
    def test_server_handles_server_without_password(self, mock_data_get):
        mock_data_get.return_value = {}
        stack_name = 'admin_pass_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)
        self.assertEqual('', server.FnGetAtt('admin_pass'))

    @mock.patch.object(resource.Resource, 'data')
    def test_server_has_admin_pass_attribute_available(self, mock_data_get):
        mock_data_get.return_value = {'admin_pass': 'foo'}
        stack_name = 'admin_pass_s'
        (tmpl, stack) = self._setup_test_stack(stack_name)

        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)
        self.assertEqual('foo', server.FnGetAtt('admin_pass'))

    def _test_server_config_drive(self, user_data, config_drive, result):
        return_server = self.fc.servers.list()[1]
        stack_name = 'no_user_data'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        properties = tmpl.t['Resources']['WebServer']['Properties']
        properties['user_data'] = user_data
        properties['config_drive'] = config_drive
        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)
        mock_servers_create = mock.Mock(return_value=return_server)
        self.fc.servers.create = mock_servers_create
        image_id = mock.ANY
        self._mock_get_image_id_success(image_id)
        scheduler.TaskRunner(server.create)()
        mock_servers_create.assert_called_with(
            image=image_id,
            flavor=mock.ANY,
            key_name=mock.ANY,
            name=mock.ANY,
            security_groups=mock.ANY,
            userdata=mock.ANY,
            scheduler_hints=mock.ANY,
            meta=mock.ANY,
            nics=mock.ANY,
            availability_zone=mock.ANY,
            block_device_mapping=mock.ANY,
            config_drive=result,
            disk_config=mock.ANY,
            reservation_id=mock.ANY,
            files=mock.ANY,
            admin_pass=mock.ANY)

    def test_server_user_data_no_config_drive(self):
        self._test_server_config_drive("my script", False, True)

    def test_server_user_data_config_drive(self):
        self._test_server_config_drive("my script", True, True)

    def test_server_no_user_data_config_drive(self):
        self._test_server_config_drive(None, True, True)

    def test_server_no_user_data_no_config_drive(self):
        self._test_server_config_drive(None, False, False)
