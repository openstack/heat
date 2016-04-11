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
from oslo_config import cfg
from oslo_utils import uuidutils
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine import resource
from heat.engine import rsrc_defn
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
        cfg.CONF.set_override('region_name_for_services', 'RegionOne',
                              enforce_type=True)
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

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        templ = template.Template(
            t, env=environment.Environment({'key_name': 'test'}))

        self.stack = parser.Stack(self.ctx, stack_name, templ,
                                  stack_id=uuidutils.generate_uuid())
        return (templ, self.stack)

    def _setup_test_server(self, return_server, name, image_id=None,
                           override_name=False, stub_create=True):
        stack_name = '%s_s' % name
        (tmpl, stack) = self._setup_test_stack(stack_name)

        tmpl.t['Resources']['WebServer']['Properties'][
            'image'] = image_id or 'CentOS 5.2'
        tmpl.t['Resources']['WebServer']['Properties'][
            'flavor'] = '256 MB Server'
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='aaaaaa')
        self.patchobject(nova.NovaClientPlugin, 'find_flavor_by_name_or_id',
                         return_value=1)
        self.patchobject(glance.GlanceClientPlugin, 'find_image_by_name_or_id',
                         return_value=1)
        server_name = '%s' % name
        if override_name:
            tmpl.t['Resources']['WebServer']['Properties'][
                'name'] = server_name

        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer(server_name,
                                          resource_defns['WebServer'],
                                          stack)
        self.patchobject(nova.NovaClientPlugin, '_create',
                         return_value=self.fc)

        self.patchobject(server, 'store_external_ports')

        if stub_create:
            self.patchobject(self.fc.servers, 'create',
                             return_value=return_server)
            # mock check_create_complete innards
            self.patchobject(self.fc.servers, 'get',
                             return_value=return_server)
        return server

    def _create_test_server(self, return_server, name, override_name=False,
                            stub_create=True):
        server = self._setup_test_server(return_server, name,
                                         stub_create=stub_create)
        scheduler.TaskRunner(server.create)()
        return server

    def _mock_metadata_os_distro(self):
        image_data = mock.Mock(metadata={'os_distro': 'centos'})
        self.fc.images.get = mock.Mock(return_value=image_data)

    def test_rackconnect_deployed(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {
            'rackconnect_automation_status': 'DEPLOYED',
            'rax_service_level_automation': 'Complete',
        }
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_deployed')
        server.context.roles = ['rack_connect']
        scheduler.TaskRunner(server.create)()
        self.assertEqual('CREATE', server.action)
        self.assertEqual('COMPLETE', server.status)

    def test_rackconnect_failed(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {
            'rackconnect_automation_status': 'FAILED',
            'rax_service_level_automation': 'Complete',
        }
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_failed')
        server.context.roles = ['rack_connect']
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: resources.test_rackconnect_failed: '
                         'RackConnect automation FAILED',
                         six.text_type(exc))

    def test_rackconnect_unprocessable(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {
            'rackconnect_automation_status': 'UNPROCESSABLE',
            'rackconnect_unprocessable_reason': 'Fake reason',
            'rax_service_level_automation': 'Complete',
        }
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_unprocessable')
        server.context.roles = ['rack_connect']
        scheduler.TaskRunner(server.create)()
        self.assertEqual('CREATE', server.action)
        self.assertEqual('COMPLETE', server.status)

    def test_rackconnect_unknown(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {
            'rackconnect_automation_status': 'FOO',
            'rax_service_level_automation': 'Complete',
        }
        server = self._setup_test_server(return_server,
                                         'test_rackconnect_unknown')
        server.context.roles = ['rack_connect']
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
                return_server.metadata.update({
                    'rackconnect_automation_status': 'DEPLOYING',
                    'rax_service_level_automation': 'Complete',
                    })
            if check_iterations[0] == 2:
                return_server.status = 'ACTIVE'
            if check_iterations[0] > 3:
                return_server.metadata.update({
                    'rackconnect_automation_status': 'DEPLOYED',
                })
            return return_server
        self.patchobject(self.fc.servers, 'get',
                         side_effect=activate_status)

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

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
            if check_iterations[0] > 2:
                return_server.metadata.update({
                    'rackconnect_automation_status': 'DEPLOYED',
                    'rax_service_level_automation': 'Complete'})

            return return_server
        self.patchobject(self.fc.servers, 'get',
                         side_effect=activate_status)
        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

    def test_rax_automation_lifecycle(self):
        return_server = self.fc.servers.list()[0]
        server = self._setup_test_server(return_server,
                                         'srv_sts_bld')
        server.resource_id = 1234
        server.context.roles = ['rack_connect']
        server.metadata = {}
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
        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

    def test_add_port_for_addresses(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation': 'Complete'}
        stack_name = 'test_stack'
        (tmpl, stack) = self._setup_test_stack(stack_name)
        resource_defns = tmpl.resource_definitions(stack)
        self.patchobject(nova.NovaClientPlugin, 'find_flavor_by_name_or_id',
                         return_value=1)
        self.patchobject(glance.GlanceClientPlugin, 'find_image_by_name_or_id',
                         return_value=1)
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

    def test_rax_automation_build_error(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation':
                                  'Build Error'}
        server = self._setup_test_server(return_server,
                                         'test_managed_cloud_build_error')
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: resources.test_managed_cloud_build_error: '
                         'Rackspace Cloud automation failed',
                         six.text_type(exc))

    def test_rax_automation_unknown(self):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation': 'FOO'}
        server = self._setup_test_server(return_server,
                                         'test_managed_cloud_unknown')
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual('Error: resources.test_managed_cloud_unknown: '
                         'Unknown Rackspace Cloud automation status: FOO',
                         six.text_type(exc))

    def _test_server_config_drive(self, user_data, config_drive, result,
                                  ud_format='RAW'):
        return_server = self.fc.servers.list()[1]
        return_server.metadata = {'rax_service_level_automation': 'Complete'}
        stack_name = 'no_user_data'
        self.patchobject(nova.NovaClientPlugin, 'find_flavor_by_name_or_id',
                         return_value=1)
        self.patchobject(glance.GlanceClientPlugin, 'find_image_by_name_or_id',
                         return_value=1)
        (tmpl, stack) = self._setup_test_stack(stack_name)
        properties = tmpl.t['Resources']['WebServer']['Properties']
        properties['user_data'] = user_data
        properties['config_drive'] = config_drive
        properties['user_data_format'] = ud_format
        properties['software_config_transport'] = "POLL_TEMP_URL"
        resource_defns = tmpl.resource_definitions(stack)
        server = cloud_server.CloudServer('WebServer',
                                          resource_defns['WebServer'], stack)
        server.metadata = {'rax_service_level_automation': 'Complete'}
        self.patchobject(server, 'store_external_ports')
        self.patchobject(server, "_populate_deployments_metadata")
        mock_servers_create = mock.Mock(return_value=return_server)
        self.fc.servers.create = mock_servers_create
        self.patchobject(self.fc.servers, 'get',
                         return_value=return_server)
        scheduler.TaskRunner(server.create)()
        mock_servers_create.assert_called_with(
            image=mock.ANY,
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

    def test_server_no_user_data_software_config(self):
        self._test_server_config_drive(None, False, True,
                                       ud_format="SOFTWARE_CONFIG")


@mock.patch.object(resource.Resource, "client_plugin")
@mock.patch.object(resource.Resource, "client")
class CloudServersValidationTests(common.HeatTestCase):
    def setUp(self):
        super(CloudServersValidationTests, self).setUp()
        resource._register_class("OS::Nova::Server", cloud_server.CloudServer)
        properties_server = {
            "image": "CentOS 5.2",
            "flavor": "256 MB Server",
            "key_name": "test",
            "user_data": "wordpress",
        }
        self.mockstack = mock.Mock()
        self.mockstack.has_cache_data.return_value = False
        self.mockstack.db_resource_get.return_value = None
        self.rsrcdef = rsrc_defn.ResourceDefinition(
            "test", cloud_server.CloudServer, properties=properties_server)

    def test_validate_no_image(self, mock_client, mock_plugin):
        properties_server = {
            "flavor": "256 MB Server",
            "key_name": "test",
            "user_data": "wordpress",
        }

        rsrcdef = rsrc_defn.ResourceDefinition(
            "test", cloud_server.CloudServer, properties=properties_server)
        mock_plugin().find_flavor_by_name_or_id.return_value = 1
        server = cloud_server.CloudServer("test", rsrcdef, self.mockstack)
        mock_boot_vol = self.patchobject(
            server, '_validate_block_device_mapping')
        mock_boot_vol.return_value = True
        self.assertIsNone(server.validate())

    def test_validate_no_image_bfv(self, mock_client, mock_plugin):
        properties_server = {
            "flavor": "256 MB Server",
            "key_name": "test",
            "user_data": "wordpress",
        }
        rsrcdef = rsrc_defn.ResourceDefinition(
            "test", cloud_server.CloudServer, properties=properties_server)

        mock_plugin().find_flavor_by_name_or_id.return_value = 1
        server = cloud_server.CloudServer("test", rsrcdef, self.mockstack)

        mock_boot_vol = self.patchobject(
            server, '_validate_block_device_mapping')
        mock_boot_vol.return_value = True

        mock_flavor = mock.Mock(ram=4)
        mock_flavor.to_dict.return_value = {
            'OS-FLV-WITH-EXT-SPECS:extra_specs': {
                'class': 'standard1',
                },
        }

        mock_plugin().get_flavor.return_value = mock_flavor
        error = self.assertRaises(
            exception.StackValidationFailed, server.validate)
        self.assertEqual(
            'Flavor 256 MB Server cannot be booted from volume.',
            six.text_type(error))

    def test_validate_bfv_volume_only(self, mock_client, mock_plugin):
        mock_plugin().find_flavor_by_name_or_id.return_value = 1
        mock_plugin().find_image_by_name_or_id.return_value = 1
        server = cloud_server.CloudServer("test", self.rsrcdef, self.mockstack)

        mock_flavor = mock.Mock(ram=4, disk=4)
        mock_flavor.to_dict.return_value = {
            'OS-FLV-WITH-EXT-SPECS:extra_specs': {
                'class': 'memory1',
                },
        }

        mock_image = mock.Mock(status='ACTIVE', min_ram=2, min_disk=1)
        mock_image.get.return_value = "memory1"

        mock_plugin().get_flavor.return_value = mock_flavor
        mock_plugin().get_image.return_value = mock_image

        error = self.assertRaises(
            exception.StackValidationFailed, server.validate)
        self.assertEqual(
            'Flavor 256 MB Server must be booted from volume, '
            'but image CentOS 5.2 was also specified.',
            six.text_type(error))

    def test_validate_image_flavor_excluded_class(self, mock_client,
                                                  mock_plugin):
        mock_plugin().find_flavor_by_name_or_id.return_value = 1
        mock_plugin().find_image_by_name_or_id.return_value = 1
        server = cloud_server.CloudServer("test", self.rsrcdef, self.mockstack)

        mock_image = mock.Mock(status='ACTIVE', min_ram=2, min_disk=1)
        mock_image.get.return_value = "!standard1, *"

        mock_flavor = mock.Mock(ram=4, disk=4)
        mock_flavor.to_dict.return_value = {
            'OS-FLV-WITH-EXT-SPECS:extra_specs': {
                'class': 'standard1',
                },
        }

        mock_plugin().get_flavor.return_value = mock_flavor
        mock_plugin().get_image.return_value = mock_image

        error = self.assertRaises(
            exception.StackValidationFailed, server.validate)
        self.assertEqual(
            'Flavor 256 MB Server cannot be used with image CentOS 5.2.',
            six.text_type(error))

    def test_validate_image_flavor_ok(self, mock_client, mock_plugin):
        mock_plugin().find_flavor_by_name_or_id.return_value = 1
        mock_plugin().find_image_by_name_or_id.return_value = 1
        server = cloud_server.CloudServer("test", self.rsrcdef, self.mockstack)

        mock_image = mock.Mock(size=1, status='ACTIVE', min_ram=2, min_disk=2)
        mock_image.get.return_value = "standard1"

        mock_flavor = mock.Mock(ram=4, disk=4)
        mock_flavor.to_dict.return_value = {
            'OS-FLV-WITH-EXT-SPECS:extra_specs': {
                'class': 'standard1',
                'disk_io_index': 1,
                },
        }

        mock_plugin().get_flavor.return_value = mock_flavor
        mock_plugin().get_image.return_value = mock_image

        self.assertIsNone(server.validate())
