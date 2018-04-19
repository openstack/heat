#
# Copyright (c) 2013 Docker, Inc.
# All Rights Reserved.
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
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import template_format
from heat.engine import resource
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

import testtools

from heat_docker.resources import docker_container
from heat_docker.tests import fake_docker_client as docker

docker_container.docker = docker


template = '''
{
    "AWSTemplateFormatVersion": "2010-09-09",
    "Description": "Test template",
    "Parameters": {},
    "Resources": {
        "Blog": {
            "Type": "DockerInc::Docker::Container",
            "Properties": {
                "image": "samalba/wordpress",
                "env": [
                    "FOO=bar"
                ]
            }
        }
    }
}
'''


class DockerContainerTest(common.HeatTestCase):

    def setUp(self):
        super(DockerContainerTest, self).setUp()
        for res_name, res_class in docker_container.resource_mapping().items():
            resource._register_class(res_name, res_class)

    def create_container(self, resource_name):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        resource = docker_container.DockerContainer(
            resource_name,
            self.stack.t.resource_definitions(self.stack)[resource_name],
            self.stack)
        self.patchobject(resource, 'get_client',
                         return_value=docker.Client())
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        return resource

    def get_container_state(self, resource):
        client = resource.get_client()
        return client.inspect_container(resource.resource_id)['State']

    def test_resource_create(self):
        container = self.create_container('Blog')
        self.assertTrue(container.resource_id)
        running = self.get_container_state(container)['Running']
        self.assertIs(True, running)
        client = container.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertIsNone(client.container_create[0]['name'])

    def test_create_with_name(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['name'] = 'super-blog'
        resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        self.patchobject(resource, 'get_client',
                         return_value=docker.Client())
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual('super-blog', client.container_create[0]['name'])

    @mock.patch.object(docker_container.DockerContainer, 'get_client')
    def test_create_failed(self, test_client):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()

        mock_client = mock.Mock()
        mock_client.inspect_container.return_value = {
            "State": {
                "ExitCode": -1
            }
        }
        mock_client.logs.return_value = "Container startup failed"
        test_client.return_value = mock_client
        docker_res = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        exc = self.assertRaises(exception.ResourceInError,
                                docker_res.check_create_complete,
                                'foo')
        self.assertIn("Container startup failed", six.text_type(exc))

    def test_start_with_bindings_and_links(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['port_bindings'] = {'80/tcp': [{'HostPort': '80'}]}
        props['links'] = {'db': 'mysql'}
        resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        self.patchobject(resource, 'get_client',
                         return_value=docker.Client())
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual({'db': 'mysql'}, client.container_start[0]['links'])
        self.assertEqual(
            {'80/tcp': [{'HostPort': '80'}]},
            client.container_start[0]['port_bindings'])

    def test_resource_attributes(self):
        container = self.create_container('Blog')
        # Test network info attributes
        self.assertEqual('172.17.42.1', container.FnGetAtt('network_gateway'))
        self.assertEqual('172.17.0.3', container.FnGetAtt('network_ip'))
        self.assertEqual('1080', container.FnGetAtt('network_tcp_ports'))
        self.assertEqual('', container.FnGetAtt('network_udp_ports'))
        # Test logs attributes
        self.assertEqual('---logs_begin---', container.FnGetAtt('logs_head'))
        self.assertEqual('---logs_end---', container.FnGetAtt('logs_tail'))
        # Test a non existing attribute
        self.assertRaises(exception.InvalidTemplateAttribute,
                          container.FnGetAtt, 'invalid_attribute')

    @testtools.skipIf(docker is None, 'docker-py not available')
    def test_resource_delete(self):
        container = self.create_container('Blog')
        scheduler.TaskRunner(container.delete)()
        self.assertEqual((container.DELETE, container.COMPLETE),
                         container.state)

        exists = True
        try:
            self.get_container_state(container)['Running']
        except docker.errors.APIError as error:
            if error.response.status_code == 404:
                exists = False
            else:
                raise

        self.assertIs(False, exists)

    @testtools.skipIf(docker is None, 'docker-py not available')
    def test_resource_delete_exception(self):
        response = mock.MagicMock()
        response.status_code = 404
        response.content = 'some content'

        container = self.create_container('Blog')
        self.patchobject(container.get_client(), 'kill',
                         side_effect=[docker.errors.APIError(
                             'Not found', response)])

        self.patchobject(container, '_get_container_status',
                         side_effect=[docker.errors.APIError(
                             'Not found', response)])
        scheduler.TaskRunner(container.delete)()
        container.get_client().kill.assert_called_once_with(
            container.resource_id)
        container._get_container_status.assert_called_once_with(
            container.resource_id)

    def test_resource_suspend_resume(self):
        container = self.create_container('Blog')
        # Test suspend
        scheduler.TaskRunner(container.suspend)()
        self.assertEqual((container.SUSPEND, container.COMPLETE),
                         container.state)
        running = self.get_container_state(container)['Running']
        self.assertIs(False, running)
        # Test resume
        scheduler.TaskRunner(container.resume)()
        self.assertEqual((container.RESUME, container.COMPLETE),
                         container.state)
        running = self.get_container_state(container)['Running']
        self.assertIs(True, running)

    def test_start_with_restart_policy_no(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['restart_policy'] = {'Name': 'no', 'MaximumRetryCount': 0}
        resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual({'Name': 'no', 'MaximumRetryCount': 0},
                         client.container_start[0]['restart_policy'])

    def test_start_with_restart_policy_on_failure(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['restart_policy'] = {'Name': 'on-failure',
                                   'MaximumRetryCount': 10}
        resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual({'Name': 'on-failure', 'MaximumRetryCount': 10},
                         client.container_start[0]['restart_policy'])

    def test_start_with_restart_policy_always(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['restart_policy'] = {'Name': 'always', 'MaximumRetryCount': 0}
        resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual({'Name': 'always', 'MaximumRetryCount': 0},
                         client.container_start[0]['restart_policy'])

    def test_start_with_caps(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['cap_add'] = ['NET_ADMIN']
        props['cap_drop'] = ['MKNOD']
        resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual(['NET_ADMIN'], client.container_start[0]['cap_add'])
        self.assertEqual(['MKNOD'], client.container_start[0]['cap_drop'])

    def test_start_with_read_only(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['read_only'] = True
        resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        get_client_mock.return_value.set_api_version('1.17')
        self.assertIsNone(resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertIs(True, client.container_start[0]['read_only'])

    def arg_for_low_api_version(self, arg, value, low_version):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props[arg] = value
        my_resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(my_resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        get_client_mock.return_value.set_api_version(low_version)
        msg = self.assertRaises(docker_container.InvalidArgForVersion,
                                my_resource.validate)
        min_version = docker_container.MIN_API_VERSION_MAP[arg]
        args = dict(arg=arg, min_version=min_version)
        expected = _('"%(arg)s" is not supported for API version '
                     '< "%(min_version)s"') % args
        self.assertEqual(expected, six.text_type(msg))

    def test_start_with_read_only_for_low_api_version(self):
        self.arg_for_low_api_version('read_only', True, '1.16')

    def test_compare_version(self):
        self.assertEqual(docker_container.compare_version('1.17', '1.17'), 0)
        self.assertEqual(docker_container.compare_version('1.17', '1.16'), -1)
        self.assertEqual(docker_container.compare_version('1.17', '1.18'), 1)

    def test_create_with_cpu_shares(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['cpu_shares'] = 512
        my_resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(my_resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(my_resource.validate())
        scheduler.TaskRunner(my_resource.create)()
        self.assertEqual((my_resource.CREATE, my_resource.COMPLETE),
                         my_resource.state)
        client = my_resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual(512, client.container_create[0]['cpu_shares'])

    def test_create_with_cpu_shares_for_low_api_version(self):
        self.arg_for_low_api_version('cpu_shares', 512, '1.7')

    def test_start_with_mapping_devices(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['devices'] = (
            [{'path_on_host': '/dev/sda',
              'path_in_container': '/dev/xvdc',
              'permissions': 'r'},
             {'path_on_host': '/dev/mapper/a_bc-d',
              'path_in_container': '/dev/xvdd',
              'permissions': 'rw'}])
        my_resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(my_resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(my_resource.validate())
        scheduler.TaskRunner(my_resource.create)()
        self.assertEqual((my_resource.CREATE, my_resource.COMPLETE),
                         my_resource.state)
        client = my_resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual(['/dev/sda:/dev/xvdc:r',
                          '/dev/mapper/a_bc-d:/dev/xvdd:rw'],
                         client.container_start[0]['devices'])

    def test_start_with_mapping_devices_also_with_privileged(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['devices'] = (
            [{'path_on_host': '/dev/sdb',
              'path_in_container': '/dev/xvdc',
              'permissions': 'r'}])
        props['privileged'] = True
        my_resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(my_resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(my_resource.validate())
        scheduler.TaskRunner(my_resource.create)()
        self.assertEqual((my_resource.CREATE, my_resource.COMPLETE),
                         my_resource.state)
        client = my_resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertNotIn('devices', client.container_start[0])

    def test_start_with_mapping_devices_for_low_api_version(self):
        value = ([{'path_on_host': '/dev/sda',
                   'path_in_container': '/dev/xvdc',
                   'permissions': 'rwm'}])
        self.arg_for_low_api_version('devices', value, '1.13')

    def test_start_with_mapping_devices_not_set_path_in_container(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['devices'] = [{'path_on_host': '/dev/sda',
                             'permissions': 'rwm'}]
        my_resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(my_resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(my_resource.validate())
        scheduler.TaskRunner(my_resource.create)()
        self.assertEqual((my_resource.CREATE, my_resource.COMPLETE),
                         my_resource.state)
        client = my_resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual(['/dev/sda:/dev/sda:rwm'],
                         client.container_start[0]['devices'])

    def test_create_with_cpu_set(self):
        t = template_format.parse(template)
        self.stack = utils.parse_stack(t)
        definition = self.stack.t.resource_definitions(self.stack)['Blog']
        props = t['Resources']['Blog']['Properties'].copy()
        props['cpu_set'] = '0-8,16-24,28'
        my_resource = docker_container.DockerContainer(
            'Blog', definition.freeze(properties=props), self.stack)
        get_client_mock = self.patchobject(my_resource, 'get_client')
        get_client_mock.return_value = docker.Client()
        self.assertIsNone(my_resource.validate())
        scheduler.TaskRunner(my_resource.create)()
        self.assertEqual((my_resource.CREATE, my_resource.COMPLETE),
                         my_resource.state)
        client = my_resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual('0-8,16-24,28',
                         client.container_create[0]['cpuset'])

    def test_create_with_cpu_set_for_low_api_version(self):
        self.arg_for_low_api_version('cpu_set', '0-8,^2', '1.11')
