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

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import scheduler
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import utils

from testtools import skipIf

from ..resources import docker_container  # noqa
from .fake_docker_client import FakeDockerClient  # noqa

docker = try_import('docker')


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


class DockerContainerTest(HeatTestCase):

    def setUp(self):
        super(DockerContainerTest, self).setUp()
        for res_name, res_class in docker_container.resource_mapping().items():
            resource._register_class(res_name, res_class)
        self.addCleanup(self.m.VerifyAll)

    def create_container(self, resource_name):
        t = template_format.parse(template)
        stack = utils.parse_stack(t)
        resource = docker_container.DockerContainer(
            resource_name,
            stack.t.resource_definitions(stack)[resource_name], stack)
        self.m.StubOutWithMock(resource, 'get_client')
        resource.get_client().MultipleTimes().AndReturn(FakeDockerClient())
        self.assertIsNone(resource.validate())
        self.m.ReplayAll()
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
        stack = utils.parse_stack(t)
        definition = stack.t.resource_definitions(stack)['Blog']
        definition['Properties']['name'] = 'super-blog'
        resource = docker_container.DockerContainer(
            'Blog', definition, stack)
        self.m.StubOutWithMock(resource, 'get_client')
        resource.get_client().MultipleTimes().AndReturn(FakeDockerClient())
        self.assertIsNone(resource.validate())
        self.m.ReplayAll()
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE),
                         resource.state)
        client = resource.get_client()
        self.assertEqual(['samalba/wordpress'], client.pulled_images)
        self.assertEqual('super-blog', client.container_create[0]['name'])

    def test_start_with_bindings_and_links(self):
        t = template_format.parse(template)
        stack = utils.parse_stack(t)
        definition = stack.t.resource_definitions(stack)['Blog']
        definition['Properties']['port_bindings'] = {
            '80/tcp': [{'HostPort': '80'}]}
        definition['Properties']['links'] = {'db': 'mysql'}
        resource = docker_container.DockerContainer(
            'Blog', definition, stack)
        self.m.StubOutWithMock(resource, 'get_client')
        resource.get_client().MultipleTimes().AndReturn(FakeDockerClient())
        self.assertIsNone(resource.validate())
        self.m.ReplayAll()
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

    def test_resource_delete(self):
        container = self.create_container('Blog')
        scheduler.TaskRunner(container.delete)()
        self.assertEqual((container.DELETE, container.COMPLETE),
                         container.state)
        running = self.get_container_state(container)['Running']
        self.assertIs(False, running)

    def test_resource_already_deleted(self):
        container = self.create_container('Blog')
        scheduler.TaskRunner(container.delete)()
        running = self.get_container_state(container)['Running']
        self.assertIs(False, running)

        scheduler.TaskRunner(container.delete)()
        self.m.VerifyAll()

    @skipIf(docker is None, 'docker-py not available')
    def test_resource_delete_exception(self):
        response = mock.MagicMock()
        response.status_code = 404
        response.content = 'some content'

        container = self.create_container('Blog')
        self.m.StubOutWithMock(container.get_client(), 'kill')
        container.get_client().kill(container.resource_id).AndRaise(
            docker.errors.APIError('Not found', response))

        self.m.StubOutWithMock(container, '_get_container_status')
        container._get_container_status(container.resource_id).AndRaise(
            docker.errors.APIError('Not found', response))

        self.m.ReplayAll()

        scheduler.TaskRunner(container.delete)()
        self.m.VerifyAll()

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
