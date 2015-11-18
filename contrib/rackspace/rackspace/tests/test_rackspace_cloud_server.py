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
from oslo_config import cfg
from oslo_utils import uuidutils
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import environment
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests.openstack.nova import fakes
from heat.tests import utils

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
      "Type": "OS::Nova::Server",
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

        # Test environment may not have pyrax client library installed and if
        # pyrax is not installed resource class would not be registered.
        # So register resource provider class explicitly for unit testing.
        resource._register_class("OS::Nova::Server",
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
        templ = template.Template(
            t, env=environment.Environment({'key_name': 'test'}))

        self.stack = parser.Stack(self.ctx, stack_name, templ,
                                  stack_id=uuidutils.generate_uuid())
        return (templ, self.stack)

    def _setup_test_server(self, return_server, name, image_id=None,
                           override_name=False, stub_create=True, exit_code=0):
        stack_name = '%s_s' % name
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'image'] = image_id or 'CentOS 5.2'
        tmpl.t['Resources']['WebServer']['Properties'][
            'flavor'] = '256 MB Server'

        server_name = '%s' % name
        if override_name:
            tmpl.t['Resources']['WebServer']['Properties'][
                'name'] = server_name

        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer(server_name,
                                          resource_defns['WebServer'],
                                          stack)
        self.patchobject(server, 'store_external_ports')

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
                block_device_mapping_v2=None,
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
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(server.id).AndReturn(return_server)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        return server

    def _mock_metadata_os_distro(self):
        image_data = mock.Mock(metadata={'os_distro': 'centos'})
        self.fc.images.get = mock.Mock(return_value=image_data)

    def test_rackconnect_deployed(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rackconnect_automation_status': 'DEPLOYED'}
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_deployed')
        server.context.roles = ['rack_connect']
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(return_server.id).MultipleTimes(
        ).AndReturn(return_server)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.assertEqual('CREATE', server.action)
        self.assertEqual('COMPLETE', server.status)
        self.m.VerifyAll()

    def test_rackconnect_failed(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rackconnect_automation_status': 'FAILED'}
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(return_server.id).MultipleTimes(
        ).AndReturn(return_server)
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_failed')
        server.context.roles = ['rack_connect']
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: resources.test_rackconnect_failed: '
                         'RackConnect automation FAILED',
                         six.text_type(exc))

    def test_rackconnect_unprocessable(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rackconnect_automation_status':
                                  'UNPROCESSABLE',
                                  'rackconnect_unprocessable_reason':
                                  'Fake reason'}
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(return_server.id).MultipleTimes(
        ).AndReturn(return_server)
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
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(return_server.id).MultipleTimes(
        ).AndReturn(return_server)
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_unknown')
        server.context.roles = ['rack_connect']
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: resources.test_rackconnect_unknown: '
                         'Unknown RackConnect automation status: FOO',
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
                return_server.metadata[
                    'rackconnect_automation_status'] = 'DEPLOYING'
            if check_iterations[0] == 2:
                return_server.status = 'ACTIVE'
            if check_iterations[0] > 3:
                return_server.metadata[
                    'rackconnect_automation_status'] = 'DEPLOYED'
            return return_server
        self.patchobject(self.fc.servers, 'get',
                         side_effect=activate_status)
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
                return_server.status = 'ACTIVE'
            if check_iterations[0] == 2:
                return_server.metadata = {}
            if check_iterations[0] > 2:
                return_server.metadata[
                    'rackconnect_automation_status'] = 'DEPLOYED'
            return return_server
        self.patchobject(self.fc.servers, 'get',
                         side_effect=activate_status)
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
                return_server.status = 'ACTIVE'
            if check_iterations[0] == 2:
                return_server.metadata = {
                    'rackconnect_automation_status': 'DEPLOYED'}
            if check_iterations[0] == 3:
                return_server.metadata = {
                    'rackconnect_automation_status': 'DEPLOYED',
                    'rax_service_level_automation': 'In Progress'}
            if check_iterations[0] > 3:
                return_server.metadata = {
                    'rackconnect_automation_status': 'DEPLOYED',
                    'rax_service_level_automation': 'Complete'}
            return return_server
        self.patchobject(self.fc.servers, 'get',
                         side_effect=activate_status)
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_add_port_for_addresses(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'test_stack'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)
        self.patchobject(server, 'store_external_ports')

        class Interface(object):
            def __init__(self, id, addresses):
                self.identifier = id
                self.addresses = addresses

            @property
            def id(self):
                return self.identifier

            @property
            def ip_addresses(self):
                return self.addresses

        interfaces = [
            {
                "id": "port-uuid-1",
                "ip_addresses": [
                    {
                        "address": "4.5.6.7",
                        "network_id": "00xx000-0xx0-0xx0-0xx0-00xxx000",
                        "network_label": "public"
                    },
                    {
                        "address": "2001:4802:7805:104:be76:4eff:fe20:2063",
                        "network_id": "00xx000-0xx0-0xx0-0xx0-00xxx000",
                        "network_label": "public"
                    }
                ],
                "mac_address": "fa:16:3e:8c:22:aa"
            },
            {
                "id": "port-uuid-2",
                "ip_addresses": [
                    {
                        "address": "5.6.9.8",
                        "network_id": "11xx1-1xx1-xx11-1xx1-11xxxx11",
                        "network_label": "public"
                    }
                ],
                "mac_address": "fa:16:3e:8c:44:cc"
            },
            {
                "id": "port-uuid-3",
                "ip_addresses": [
                    {
                        "address": "10.13.12.13",
                        "network_id": "1xx1-1xx1-xx11-1xx1-11xxxx11",
                        "network_label": "private"
                    }
                ],
                "mac_address": "fa:16:3e:8c:44:dd"
            }
        ]

        ifaces = [Interface(i['id'], i['ip_addresses']) for i in interfaces]
        expected = {
            'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa':
            [{'OS-EXT-IPS-MAC:mac_addr': 'fa:16:3e:8c:22:aa',
              'addr': '4.5.6.7',
              'port': 'port-uuid-1',
              'version': 4},
             {'OS-EXT-IPS-MAC:mac_addr': 'fa:16:3e:8c:33:bb',
              'addr': '5.6.9.8',
              'port': 'port-uuid-2',
              'version': 4}],

            'private': [{'OS-EXT-IPS-MAC:mac_addr': 'fa:16:3e:8c:44:cc',
                         'addr': '10.13.12.13',
                         'port': 'port-uuid-3',
                         'version': 4}],
            'public': [{'OS-EXT-IPS-MAC:mac_addr': 'fa:16:3e:8c:22:aa',
                        'addr': '4.5.6.7',
                        'port': 'port-uuid-1',
                        'version': 4},
                       {'OS-EXT-IPS-MAC:mac_addr': 'fa:16:3e:8c:33:bb',
                        'addr': '5.6.9.8',
                        'port': 'port-uuid-2',
                        'version': 4}]}

        server.client = mock.Mock()
        mock_client = mock.Mock()
        server.client.return_value = mock_client
        mock_ext = mock_client.os_virtual_interfacesv2_python_novaclient_ext
        mock_ext.list.return_value = ifaces
        resp = server._add_port_for_address(return_server)
        self.assertEqual(expected, resp)

    def test_managed_cloud_build_error(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation':
                                  'Build Error'}
        server = self._setup_test_server(return_server,
                                         'test_managed_cloud_build_error')
        server.context.roles = ['rax_managed']
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(return_server.id).MultipleTimes(
        ).AndReturn(return_server)
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: resources.test_managed_cloud_build_error: '
                         'Managed Cloud automation failed',
                         six.text_type(exc))

    def test_managed_cloud_unknown(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation': 'FOO'}
        server = self._setup_test_server(return_server,
                                         'test_managed_cloud_unknown')
        server.context.roles = ['rax_managed']
        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.fc.servers.get(return_server.id).MultipleTimes(
        ).AndReturn(return_server)
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: resources.test_managed_cloud_unknown: '
                         'Unknown Managed Cloud automation status: FOO',
                         six.text_type(exc))

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
        self.patchobject(server, 'store_external_ports')
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
            block_device_mapping_v2=mock.ANY,
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
