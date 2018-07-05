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

from oslo_serialization import jsonutils
from oslo_utils import uuidutils
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import heat_plugin
from heat.engine.clients.os import swift
from heat.engine.clients.os import zaqar
from heat.engine import environment
from heat.engine.resources.openstack.heat import deployed_server
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils

ds_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_TEMP_URL
"""

server_sc_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_SERVER_CFN
"""

server_heat_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_SERVER_HEAT
"""

server_zaqar_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: ZAQAR_MESSAGE
"""

ds_deployment_data_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_TEMP_URL
      deployment_swift_data:
        container: my-custom-container
        object: my-custom-object
"""

ds_deployment_data_bad_container_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_TEMP_URL
      deployment_swift_data:
        container: ''
        object: 'my-custom-object'
"""

ds_deployment_data_bad_object_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_TEMP_URL
      deployment_swift_data:
        container: 'my-custom-container'
        object: ''
"""

ds_deployment_data_none_container_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_TEMP_URL
      deployment_swift_data:
        container: 0
        object: 'my-custom-object'
"""

ds_deployment_data_none_object_tmpl = """
heat_template_version: 2015-10-15
resources:
  server:
    type: OS::Heat::DeployedServer
    properties:
      software_config_transport: POLL_TEMP_URL
      deployment_swift_data:
        container: 'my-custom-container'
        object: 0
"""


class DeployedServersTest(common.HeatTestCase):
    def _create_test_server(self, name, override_name=False):
        server = self._setup_test_server(name, override_name)
        scheduler.TaskRunner(server.create)()
        return server

    def _setup_test_stack(self, stack_name, test_templ=ds_tmpl):
        t = template_format.parse(test_templ)
        tmpl = template.Template(t, env=environment.Environment())
        stack = parser.Stack(utils.dummy_context(region_name="RegionOne"),
                             stack_name, tmpl,
                             stack_id=uuidutils.generate_uuid(),
                             stack_user_project_id='8888')
        return (tmpl, stack)

    def _server_create_software_config_poll_temp_url(self,
                                                     server_name='server'):
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(stack_name)

        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'POLL_TEMP_URL'
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            server_name, resource_defns[server_name], stack)

        sc = mock.Mock()
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.2'

        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=sc)
        scheduler.TaskRunner(server.create)()
        # self._create_test_server(server_name)
        metadata_put_url = server.data().get('metadata_put_url')
        md = server.metadata_get()
        metadata_url = md['os-collect-config']['request']['metadata_url']
        self.assertNotEqual(metadata_url, metadata_put_url)

        container_name = server.physical_resource_name()
        object_name = server.data().get('metadata_object_name')
        self.assertTrue(uuidutils.is_uuid_like(object_name))
        test_path = '/v1/AUTH_test_tenant_id/%s/%s' % (
            server.physical_resource_name(), object_name)
        self.assertEqual(test_path, urlparse.urlparse(metadata_put_url).path)
        self.assertEqual(test_path, urlparse.urlparse(metadata_url).path)
        sc.put_object.assert_called_once_with(
            container_name, object_name, jsonutils.dumps(md))

        sc.head_container.return_value = {'x-container-object-count': '0'}
        server._delete_temp_url()
        sc.delete_object.assert_called_once_with(container_name, object_name)
        sc.head_container.assert_called_once_with(container_name)
        sc.delete_container.assert_called_once_with(container_name)
        return metadata_url, server

    def test_server_create_deployment_swift_data(self):
        server_name = 'server'
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(
            stack_name,
            ds_deployment_data_tmpl)

        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'POLL_TEMP_URL'
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            server_name, resource_defns[server_name], stack)

        sc = mock.Mock()
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.2'

        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=sc)
        scheduler.TaskRunner(server.create)()
        # self._create_test_server(server_name)
        metadata_put_url = server.data().get('metadata_put_url')
        md = server.metadata_get()
        metadata_url = md['os-collect-config']['request']['metadata_url']
        self.assertNotEqual(metadata_url, metadata_put_url)

        container_name = 'my-custom-container'
        object_name = 'my-custom-object'
        test_path = '/v1/AUTH_test_tenant_id/%s/%s' % (
            container_name, object_name)
        self.assertEqual(test_path, urlparse.urlparse(metadata_put_url).path)
        self.assertEqual(test_path, urlparse.urlparse(metadata_url).path)
        sc.put_object.assert_called_once_with(
            container_name, object_name, jsonutils.dumps(md))

        sc.head_container.return_value = {'x-container-object-count': '0'}
        server._delete_temp_url()
        sc.delete_object.assert_called_once_with(container_name, object_name)
        sc.head_container.assert_called_once_with(container_name)
        sc.delete_container.assert_called_once_with(container_name)
        return metadata_url, server

    def test_server_create_deployment_swift_data_bad_container(self):
        server_name = 'server'
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(
            stack_name,
            ds_deployment_data_bad_container_tmpl)

        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'POLL_TEMP_URL'
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            server_name, resource_defns[server_name], stack)

        self.assertRaises(exception.StackValidationFailed, server.validate)

    def test_server_create_deployment_swift_data_bad_object(self):
        server_name = 'server'
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(
            stack_name,
            ds_deployment_data_bad_object_tmpl)

        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'POLL_TEMP_URL'
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            server_name, resource_defns[server_name], stack)

        self.assertRaises(exception.StackValidationFailed, server.validate)

    def test_server_create_deployment_swift_data_none_container(self):
        server_name = 'server'
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(
            stack_name,
            ds_deployment_data_none_container_tmpl)

        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'POLL_TEMP_URL'
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            server_name, resource_defns[server_name], stack)

        sc = mock.Mock()
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.2'

        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=sc)
        scheduler.TaskRunner(server.create)()
        # self._create_test_server(server_name)
        metadata_put_url = server.data().get('metadata_put_url')
        md = server.metadata_get()
        metadata_url = md['os-collect-config']['request']['metadata_url']
        self.assertNotEqual(metadata_url, metadata_put_url)

        container_name = '0'
        object_name = 'my-custom-object'
        test_path = '/v1/AUTH_test_tenant_id/%s/%s' % (
            container_name, object_name)
        self.assertEqual(test_path, urlparse.urlparse(metadata_put_url).path)
        self.assertEqual(test_path, urlparse.urlparse(metadata_url).path)
        sc.put_object.assert_called_once_with(
            container_name, object_name, jsonutils.dumps(md))

        sc.head_container.return_value = {'x-container-object-count': '0'}
        server._delete_temp_url()
        sc.delete_object.assert_called_once_with(container_name, object_name)
        sc.head_container.assert_called_once_with(container_name)
        sc.delete_container.assert_called_once_with(container_name)
        return metadata_url, server

    def test_server_create_deployment_swift_data_none_object(self):
        server_name = 'server'
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(
            stack_name,
            ds_deployment_data_none_object_tmpl)

        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'POLL_TEMP_URL'
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            server_name, resource_defns[server_name], stack)

        sc = mock.Mock()
        sc.head_account.return_value = {
            'x-account-meta-temp-url-key': 'secrit'
        }
        sc.url = 'http://192.0.2.2'

        self.patchobject(swift.SwiftClientPlugin, '_create',
                         return_value=sc)
        scheduler.TaskRunner(server.create)()
        # self._create_test_server(server_name)
        metadata_put_url = server.data().get('metadata_put_url')
        md = server.metadata_get()
        metadata_url = md['os-collect-config']['request']['metadata_url']
        self.assertNotEqual(metadata_url, metadata_put_url)

        container_name = 'my-custom-container'
        object_name = '0'
        test_path = '/v1/AUTH_test_tenant_id/%s/%s' % (
            container_name, object_name)
        self.assertEqual(test_path, urlparse.urlparse(metadata_put_url).path)
        self.assertEqual(test_path, urlparse.urlparse(metadata_url).path)
        sc.put_object.assert_called_once_with(
            container_name, object_name, jsonutils.dumps(md))

        sc.head_container.return_value = {'x-container-object-count': '0'}
        server._delete_temp_url()
        sc.delete_object.assert_called_once_with(container_name, object_name)
        sc.head_container.assert_called_once_with(container_name)
        sc.delete_container.assert_called_once_with(container_name)
        return metadata_url, server

    def test_server_create_software_config_poll_temp_url(self):
        metadata_url, server = (
            self._server_create_software_config_poll_temp_url())

        self.assertEqual({
            'os-collect-config': {
                'request': {
                    'metadata_url': metadata_url
                },
                'collectors': ['request', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config(self,
                                       server_name='server_sc',
                                       md=None,
                                       ret_tmpl=False):
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(stack_name, server_sc_tmpl)
        self.stack = stack
        self.server_props = tmpl.t['resources']['server']['properties']
        if md is not None:
            tmpl.t['resources']['server']['metadata'] = md

        stack.stack_user_project_id = '8888'
        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            'server', resource_defns['server'], stack)
        self.patchobject(server, 'heat')
        scheduler.TaskRunner(server.create)()

        self.assertEqual('4567', server.access_key)
        self.assertEqual('8901', server.secret_key)
        self.assertEqual('1234', server._get_user_id())
        self.assertEqual('POLL_SERVER_CFN',
                         server.properties.get('software_config_transport'))

        self.assertTrue(stack.access_allowed('4567', 'server'))
        self.assertFalse(stack.access_allowed('45678', 'server'))
        self.assertFalse(stack.access_allowed('4567', 'wserver'))
        if ret_tmpl:
            return server, tmpl
        else:
            return server

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_server_create_software_config(self, fake_url):
        fake_url.return_value = 'the-cfn-url'
        server = self._server_create_software_config()

        self.assertEqual({
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': 'the-cfn-url/v1/',
                    'path': 'server.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'server_sc_s'
                },
                'collectors': ['cfn', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    @mock.patch.object(heat_plugin.HeatClientPlugin, 'url_for')
    def test_server_create_software_config_metadata(self, fake_url):
        md = {'os-collect-config': {'polling_interval': 10}}
        fake_url.return_value = 'the-cfn-url'
        server = self._server_create_software_config(md=md)

        self.assertEqual({
            'os-collect-config': {
                'cfn': {
                    'access_key_id': '4567',
                    'metadata_url': 'the-cfn-url/v1/',
                    'path': 'server.Metadata',
                    'secret_access_key': '8901',
                    'stack_name': 'server_sc_s'
                },
                'collectors': ['cfn', 'local'],
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config_poll_heat(self,
                                                 server_name='server_heat',
                                                 md=None):
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(stack_name, server_heat_tmpl)
        self.stack = stack
        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'POLL_SERVER_HEAT'
        if md is not None:
            tmpl.t['resources']['server']['metadata'] = md
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            'server', resource_defns['server'], stack)

        scheduler.TaskRunner(server.create)()
        self.assertEqual('1234', server._get_user_id())

        self.assertTrue(stack.access_allowed('1234', 'server'))
        self.assertFalse(stack.access_allowed('45678', 'server'))
        self.assertFalse(stack.access_allowed('4567', 'wserver'))
        return stack, server

    def test_server_software_config_poll_heat(self):
        stack, server = self._server_create_software_config_poll_heat()
        md = {
            'os-collect-config': {
                'heat': {
                    'auth_url': 'http://server.test:5000/v2.0',
                    'password': server.password,
                    'project_id': '8888',
                    'region_name': 'RegionOne',
                    'resource_name': 'server',
                    'stack_id': 'server_heat_s/%s' % stack.id,
                    'user_id': '1234'
                },
                'collectors': ['heat', 'local']
            },
            'deployments': []
        }

        self.assertEqual(md, server.metadata_get())
        # update resource.metadata
        md1 = {'os-collect-config': {'polling_interval': 10}}
        server.stack.t.t['resources']['server']['metadata'] = md1
        resource_defns = server.stack.t.resource_definitions(server.stack)
        scheduler.TaskRunner(server.update, resource_defns['server'])()

        occ = md['os-collect-config']
        occ.update(md1['os-collect-config'])
        # os-collect-config merged
        self.assertEqual(md, server.metadata_get())

    def test_server_create_software_config_poll_heat_metadata(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        stack, server = self._server_create_software_config_poll_heat(md=md)

        self.assertEqual({
            'os-collect-config': {
                'heat': {
                    'auth_url': 'http://server.test:5000/v2.0',
                    'password': server.password,
                    'project_id': '8888',
                    'region_name': 'RegionOne',
                    'resource_name': 'server',
                    'stack_id': 'server_heat_s/%s' % stack.id,
                    'user_id': '1234'
                },
                'collectors': ['heat', 'local'],
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def _server_create_software_config_zaqar(self,
                                             server_name='server_zaqar',
                                             md=None):
        stack_name = '%s_s' % server_name
        (tmpl, stack) = self._setup_test_stack(stack_name, server_zaqar_tmpl)
        self.stack = stack
        props = tmpl.t['resources']['server']['properties']
        props['software_config_transport'] = 'ZAQAR_MESSAGE'
        if md is not None:
            tmpl.t['resources']['server']['metadata'] = md
        self.server_props = props

        resource_defns = tmpl.resource_definitions(stack)
        server = deployed_server.DeployedServer(
            'server', resource_defns['server'], stack)

        zcc = self.patchobject(zaqar.ZaqarClientPlugin, 'create_for_tenant')
        zc = mock.Mock()
        zcc.return_value = zc
        queue = mock.Mock()
        zc.queue.return_value = queue
        scheduler.TaskRunner(server.create)()

        metadata_queue_id = server.data().get('metadata_queue_id')
        md = server.metadata_get()
        queue_id = md['os-collect-config']['zaqar']['queue_id']
        self.assertEqual(queue_id, metadata_queue_id)

        zc.queue.assert_called_once_with(queue_id)
        queue.post.assert_called_once_with(
            {'body': server.metadata_get(), 'ttl': 3600})

        zc.queue.reset_mock()

        server._delete_queue()

        zc.queue.assert_called_once_with(queue_id)
        zc.queue(queue_id).delete.assert_called_once_with()
        return queue_id, server

    def test_server_create_software_config_zaqar(self):
        queue_id, server = self._server_create_software_config_zaqar()
        self.assertEqual({
            'os-collect-config': {
                'zaqar': {
                    'user_id': '1234',
                    'password': server.password,
                    'auth_url': 'http://server.test:5000/v2.0',
                    'project_id': '8888',
                    'region_name': 'RegionOne',
                    'queue_id': queue_id
                },
                'collectors': ['zaqar', 'local']
            },
            'deployments': []
        }, server.metadata_get())

    def test_server_create_software_config_zaqar_metadata(self):
        md = {'os-collect-config': {'polling_interval': 10}}
        queue_id, server = self._server_create_software_config_zaqar(md=md)
        self.assertEqual({
            'os-collect-config': {
                'zaqar': {
                    'user_id': '1234',
                    'password': server.password,
                    'auth_url': 'http://server.test:5000/v2.0',
                    'project_id': '8888',
                    'region_name': 'RegionOne',
                    'queue_id': queue_id
                },
                'collectors': ['zaqar', 'local'],
                'polling_interval': 10
            },
            'deployments': []
        }, server.metadata_get())

    def test_resolve_attribute_os_collect_config(self):
        metadata_url, server = (
            self._server_create_software_config_poll_temp_url())

        # FnGetAtt usage belows requires the resource to have a stack set
        (tmpl, stack) = self._setup_test_stack('stack_name')
        server.stack = stack

        self.assertEqual({
            'request': {
                'metadata_url': metadata_url
            },
            'collectors': ['request', 'local']
        }, server.FnGetAtt('os_collect_config'))
