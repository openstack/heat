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

import mox
import paramiko

from heat.common import exception
from heat.common import template_format
from heat.db import api as db_api
from heat.engine import clients
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine.resources import image
from heat.engine import scheduler
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
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

rsa_key = """-----BEGIN RSA PRIVATE KEY-----
MIICWwIBAAKBgQDibWGom/83F2xYfVylBZhUbREiVlw42X7afUuHzNJuh/5EyhXQ
BmBHjVGL1mxZY4GoISrxIkW1jVmTXbm8FknIlS3jxEOC+xF3IkLBtmZEkFVLOUCv
Fpru1xThFS0L/pRttiTWLm+dsjboCV4qtg/+y30O0RJ5AAFgGkoVs8idrQIDAQAB
AoGAQU/7037r5yBCiGPgzVkHz5KGVrlCcMOL68ood0uFh4yCs6T3FcJBE2KYGxYG
uuIRDEZE9LlGElBrfi6S3MYxEbewITK9Li1cr8K0fJlIbg5PI1MxwiTXzG7i0f8Y
trtZjo/fs8XNSS4xlGWCUgtiNXvLS6wxyDGGbqeh1BmETgECQQDmoPJ3h5kuZguA
o7B+iTaKXqyWPf0ImsZ0UQYBgnEWTaZEh8W0015jP55mndALWA9pmhHJm+BC/Hfe
Kp6jtVyxAkEA+1YctDe62u5pXU/GK8UfDJwi4m1VxUfASrlxh+ALag9knwe6Dlev
EKKIe8R6HZs2zavaJs6dddxHRcIi8rXfvQJAW6octOVwPMDSUY69140x4E1Ay3ZX
29OojRKnEHKIABVcwGA2dGiOW2Qt0RtoVRnrBk32Q+twdy9hdSv7YZX0AQJAVDaj
QYNW2Zp+tWRQa0QORkRer+2gioyjEqaWMsfQK0ZjGaIWJk4c+37qKkZIAHmMYFeP
recW/XHEc8w7t4VXJQJAevSyciBfFcWMZTwlqq8wXNMCRLJt5CxvO4gSO+hPNrDe
gDZkz7KcZC7TkO0NYVRssA6/84mCqx6QHpKaYNG9kg==
-----END RSA PRIVATE KEY-----
"""


class CloudServersTest(HeatTestCase):
    def setUp(self):
        super(CloudServersTest, self).setUp()
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()
        # Test environment may not have pyrax client library installed and if
        # pyrax is not installed resource class would not be registered.
        # So register resource provider class explicitly for unit testing.
        resource._register_class("Rackspace::Cloud::Server",
                                 cloud_server.CloudServer)

    def _mock_ssh_sftp(self, exit_code=0):
        # SSH
        self.m.StubOutWithMock(paramiko, "SSHClient")
        self.m.StubOutWithMock(paramiko, "MissingHostKeyPolicy")
        ssh = self.m.CreateMockAnything()
        paramiko.SSHClient().AndReturn(ssh)
        paramiko.MissingHostKeyPolicy()
        ssh.set_missing_host_key_policy(None)
        ssh.connect(mox.IgnoreArg(),
                    key_filename=mox.IgnoreArg(),
                    username='root')
        fake_chan = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko.SSHClient, "get_transport")
        chan = ssh.get_transport().AndReturn(fake_chan)
        fake_chan_session = self.m.CreateMockAnything()
        chan_session = chan.open_session().AndReturn(fake_chan_session)
        fake_chan_session.settimeout(3600.0)
        chan_session.exec_command(mox.IgnoreArg())
        fake_chan_session.recv(1024)
        chan_session.recv_exit_status().AndReturn(exit_code)
        fake_chan_session.close()
        ssh.close()

        # SFTP
        self.m.StubOutWithMock(paramiko, "Transport")
        transport = self.m.CreateMockAnything()
        paramiko.Transport((mox.IgnoreArg(), 22)).AndReturn(transport)
        transport.connect(hostkey=None, username="root", pkey=mox.IgnoreArg())
        sftp = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko, "SFTPClient")
        paramiko.SFTPClient.from_transport(transport).AndReturn(sftp)
        sftp_file = self.m.CreateMockAnything()
        sftp.open(mox.IgnoreArg(), 'w').MultipleTimes().AndReturn(sftp_file)
        sftp_file.write(mox.IgnoreArg()).MultipleTimes()
        sftp_file.close().MultipleTimes()
        sftp.close()
        transport.close()

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment({'key_name': 'test'}),
                             stack_id=uuidutils.generate_uuid())
        return (t, stack)

    def _setup_test_server(self, return_server, name, image_id=None,
                           override_name=False, stub_create=True, exit_code=0):
        stack_name = '%s_s' % name
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['image'] = \
            image_id or 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['flavor'] = \
            '256 MB Server'

        server_name = '%s' % name
        if override_name:
            t['Resources']['WebServer']['Properties']['name'] = \
                server_name

        server = cloud_server.CloudServer(server_name,
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(cloud_server.CloudServer, "nova")
        cloud_server.CloudServer.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        return_server.adminPass = "foobar"
        server._private_key = rsa_key
        server.t = server.stack.resolve_runtime_data(server.t)

        if stub_create:
            self.m.StubOutWithMock(self.fc.servers, 'create')
            self.fc.servers.create(
                image=1,
                flavor=1,
                key_name=None,
                name=override_name and server.name or utils.PhysName(
                    stack_name, server.name),
                security_groups=[],
                userdata=mox.IgnoreArg(),
                scheduler_hints=None,
                meta=None,
                nics=None,
                availability_zone=None,
                block_device_mapping=None,
                config_drive=None,
                disk_config=None,
                reservation_id=None,
                files=mox.IgnoreArg(),
                admin_pass=None).AndReturn(return_server)

        self.m.StubOutWithMock(cloud_server.CloudServer, 'script')
        cloud_server.CloudServer.script = "foobar"

        self._mock_ssh_sftp(exit_code)
        return server

    def _create_test_server(self, return_server, name, override_name=False,
                            stub_create=True, exit_code=0):
        server = self._setup_test_server(return_server, name,
                                         stub_create=stub_create,
                                         exit_code=exit_code)
        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        return server

    def _update_test_server(self, return_server, name, exit_code=0):
        self._mock_ssh_sftp(exit_code)
        self.m.StubOutWithMock(cloud_server.CloudServer, "nova")
        cloud_server.CloudServer.nova().MultipleTimes().AndReturn(self.fc)

    def _mock_metadata_os_distro(self):
        image_data = self.m.CreateMockAnything()
        image_data.metadata = {'os_distro': 'centos'}
        self.m.StubOutWithMock(self.fc.images, 'get')
        self.fc.images.get(mox.IgnoreArg()).MultipleTimes().\
            AndReturn(image_data)

    def test_script_raw_userdata(self):
        stack_name = 'raw_userdata_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['user_data_format'] = \
            'RAW'

        server = cloud_server.CloudServer('WebServer',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, "nova")
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self._mock_metadata_os_distro()
        self.m.ReplayAll()

        self.assertNotIn("/var/lib/cloud/data/cfn-userdata", server.script)
        self.m.VerifyAll()

    def test_script_cfntools_userdata(self):
        stack_name = 'raw_userdata_s'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['user_data_format'] = \
            'HEAT_CFNTOOLS'

        server = cloud_server.CloudServer('WebServer',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, "nova")
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self._mock_metadata_os_distro()
        self.m.ReplayAll()

        self.assertIn("/var/lib/cloud/data/cfn-userdata", server.script)
        self.m.VerifyAll()

    def test_validate_no_script_okay(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['image'] = '1'
        server = cloud_server.CloudServer('server_create_image_err',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(server.__class__, 'script')
        server.script = None

        self.m.StubOutWithMock(server.__class__, 'has_userdata')
        server.has_userdata = False

        self.m.StubOutWithMock(uuidutils, "is_uuid_like")
        uuidutils.is_uuid_like('1').MultipleTimes().AndReturn(True)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())

        self.m.VerifyAll()

    def test_validate_disallowed_personality(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['personality'] = \
            {"/fake/path1": "fake contents1",
             "/fake/path2": "fake_contents2",
             "/fake/path3": "fake_contents3",
             "/root/.ssh/authorized_keys": "fake_contents4"}
        server = cloud_server.CloudServer('server_create_image_err',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server.__class__, 'script')
        server.script = None

        self.m.StubOutWithMock(server.__class__, 'has_userdata')
        server.has_userdata = False

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, "nova")
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual("The personality property may not contain a "
                         "key of \"/root/.ssh/authorized_keys\"", str(exc))
        self.m.VerifyAll()

    def test_user_personality(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['personality'] = \
            {"/fake/path1": "fake contents1",
             "/fake/path2": "fake_contents2",
             "/fake/path3": "fake_contents3"}
        server = cloud_server.CloudServer('server_create_image_err',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server.__class__, 'script')
        server.script = None

        self.m.StubOutWithMock(server.__class__, 'has_userdata')
        server.has_userdata = False

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        self.assertIsNone(server.validate())

        expected_personality = {'/fake/path1': 'fake contents1',
                                '/fake/path3': 'fake_contents3',
                                '/fake/path2': 'fake_contents2',
                                '/root/.ssh/authorized_keys': mox.IgnoreArg()}
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name=None,
            name=utils.PhysName(stack_name, server.name),
            security_groups=[],
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=None, nics=None, availability_zone=None,
            block_device_mapping=None, config_drive=None,
            disk_config=None, reservation_id=None,
            files=expected_personality,
            admin_pass=None).AndReturn(return_server)

        self.m.ReplayAll()
        scheduler.TaskRunner(server.create)()
        self.m.VerifyAll()

    def test_validate_no_script_not_okay(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create a server with non-existent image ID
        t['Resources']['WebServer']['Properties']['image'] = '1'
        server = cloud_server.CloudServer('server_create_image_err',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(image.ImageConstraint, "validate")
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

        self.m.StubOutWithMock(server.__class__, 'script')
        server.script = None

        self.m.StubOutWithMock(server.__class__, 'has_userdata')
        server.has_userdata = True
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertIn("user_data is not supported", str(exc))
        self.m.VerifyAll()

    def test_validate_with_bootable_vol_and_userdata(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create a server without an image
        del t['Resources']['WebServer']['Properties']['image']
        t['Resources']['WebServer']['Properties']['block_device_mapping'] = \
            [{
                "device_name": u'vda',
                "volume_id": "5d7e27da-6703-4f7e-9f94-1f67abef734c",
                "delete_on_termination": False
            }]
        server = cloud_server.CloudServer('server_create_image_err',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server.__class__, 'has_userdata')
        server.has_userdata = True

        self.m.StubOutWithMock(cloud_server.CloudServer, "nova")
        cloud_server.CloudServer.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertIn("user_data scripts are not supported with bootable "
                      "volumes", str(exc))
        self.m.VerifyAll()

    def test_private_key(self):
        stack_name = 'test_private_key'
        (t, stack) = self._setup_test_stack(stack_name)
        server = cloud_server.CloudServer('server_private_key',
                                          t['Resources']['WebServer'],
                                          stack)

        # This gives the fake cloud server an id and created_time attribute
        server._store_or_update(server.CREATE, server.IN_PROGRESS,
                                'test_store')

        server.private_key = 'fake private key'
        self.ctx = utils.dummy_context()
        rs = db_api.resource_get_by_name_and_stack(self.ctx,
                                                   'server_private_key',
                                                   stack.id)
        encrypted_key = rs.data[0]['value']
        self.assertNotEqual(encrypted_key, "fake private key")
        decrypted_key = server.private_key
        self.assertEqual("fake private key", decrypted_key)

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
        self.assertEqual('Error: RackConnect automation FAILED', str(exc))

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
                         str(exc))

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
        self.assertEqual('Error: Managed Cloud automation failed', str(exc))

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
                         str(exc))

    def test_create_heatscript_nonzero_exit_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server, 'test_create_image_id',
                                         exit_code=1)
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual("Error: The heat-script.sh script exited with a "
                         "non-zero exit status.  To see the error message, "
                         "log into the server at 192.0.2.0 and view "
                         "/root/heat-script.log", str(exc))
        self.m.VerifyAll()

    def test_create_cfnuserdata_nonzero_exit_status(self):
        return_server = self.fc.servers.list()[1]
        server = self._setup_test_server(return_server, 'test_create_image_id',
                                         exit_code=42)
        self.m.ReplayAll()
        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual("Error: The cfn-userdata script exited with a "
                         "non-zero exit status.  To see the error message, "
                         "log into the server at 192.0.2.0 and view "
                         "/root/cfn-userdata.log", str(exc))
        self.m.VerifyAll()

    def test_validate_too_many_personality_rackspace(self):
        stack_name = 'srv_val'
        (t, stack) = self._setup_test_stack(stack_name)

        # create an server with non exist image Id
        t['Resources']['WebServer']['Properties']['personality'] = \
            {"/fake/path1": "fake contents1",
             "/fake/path2": "fake_contents2",
             "/fake/path3": "fake_contents3",
             "/fake/path4": "fake_contents4",
             "/fake/path5": "fake_contents5"}
        server = cloud_server.CloudServer('server_create_image_err',
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(server.__class__, 'script')
        server.script = None

        self.m.StubOutWithMock(server.__class__, 'has_userdata')
        server.has_userdata = False

        self.m.StubOutWithMock(server, 'nova')
        server.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, "nova")
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.ReplayAll()

        exc = self.assertRaises(exception.StackValidationFailed,
                                server.validate)
        self.assertEqual("The personality property may not contain "
                         "greater than 4 entries.", str(exc))
        self.m.VerifyAll()

    def test_ssh_exception_recovered(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'test_create_ssh_exception_recovered'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['flavor'] = '256 MB Server'

        server_name = 'test_create_ssh_exception_server'
        server = cloud_server.CloudServer(server_name,
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(cloud_server.CloudServer, "nova")
        cloud_server.CloudServer.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server._private_key = rsa_key
        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1,
            flavor=1,
            key_name=None,
            name=mox.IgnoreArg(),
            security_groups=[],
            userdata=mox.IgnoreArg(),
            scheduler_hints=None,
            meta=None,
            nics=None,
            availability_zone=None,
            block_device_mapping=None,
            config_drive=None,
            disk_config=None,
            reservation_id=None,
            files=mox.IgnoreArg(),
            admin_pass=None).AndReturn(return_server)

        self.m.StubOutWithMock(cloud_server.CloudServer, 'script')
        cloud_server.CloudServer.script = "foobar"

        # Make paramiko raise an SSHException the first time
        self.m.StubOutWithMock(paramiko, "Transport")
        paramiko.Transport((mox.IgnoreArg(), 22)).AndRaise(
            paramiko.SSHException())

        transport = self.m.CreateMockAnything()

        # The second time it works
        paramiko.Transport((mox.IgnoreArg(), 22)).AndReturn(transport)

        transport.connect(hostkey=None, username="root", pkey=mox.IgnoreArg())
        sftp = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko, "SFTPClient")
        paramiko.SFTPClient.from_transport(transport).AndReturn(sftp)
        sftp_file = self.m.CreateMockAnything()
        sftp.open(mox.IgnoreArg(), 'w').MultipleTimes().AndReturn(sftp_file)
        sftp_file.write(mox.IgnoreArg()).MultipleTimes()
        sftp_file.close().MultipleTimes()
        sftp.close()
        transport.close()

        self.m.StubOutWithMock(paramiko, "SSHClient")
        self.m.StubOutWithMock(paramiko, "MissingHostKeyPolicy")
        ssh = self.m.CreateMockAnything()
        paramiko.SSHClient().AndReturn(ssh)
        paramiko.MissingHostKeyPolicy()
        ssh.set_missing_host_key_policy(None)
        ssh.connect(mox.IgnoreArg(),
                    key_filename=mox.IgnoreArg(),
                    username='root')
        fake_chan = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko.SSHClient, "get_transport")
        chan = ssh.get_transport().AndReturn(fake_chan)
        fake_chan_session = self.m.CreateMockAnything()
        chan_session = chan.open_session().AndReturn(fake_chan_session)
        fake_chan_session.settimeout(3600.0)
        chan_session.exec_command(mox.IgnoreArg())
        fake_chan_session.recv(1024)
        chan_session.recv_exit_status().AndReturn(0)
        fake_chan_session.close()
        ssh.close()
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_ssh_exception_failed(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'test_create_ssh_exception_failed'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['flavor'] = '256 MB Server'

        server_name = 'test_create_ssh_exception_server'
        server = cloud_server.CloudServer(server_name,
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(cloud_server.CloudServer, "nova")
        cloud_server.CloudServer.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server._private_key = rsa_key
        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1,
            flavor=1,
            key_name=None,
            name=mox.IgnoreArg(),
            security_groups=[],
            userdata=mox.IgnoreArg(),
            scheduler_hints=None,
            meta=None,
            nics=None,
            availability_zone=None,
            block_device_mapping=None,
            config_drive=None,
            disk_config=None,
            reservation_id=None,
            files=mox.IgnoreArg(),
            admin_pass=None).AndReturn(return_server)

        self.m.StubOutWithMock(cloud_server.CloudServer, 'script')
        cloud_server.CloudServer.script = "foobar"

        # Make paramiko raise an SSHException every time
        self.m.StubOutWithMock(paramiko, "Transport")
        paramiko.Transport((mox.IgnoreArg(), 22)).MultipleTimes().AndRaise(
            paramiko.SSHException())
        self.m.ReplayAll()

        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual("Error: Failed to establish SSH connection after 30 "
                         "tries", str(exc))

        self.m.VerifyAll()

    def test_eof_error_recovered(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'test_create_ssh_exception_recovered'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['flavor'] = '256 MB Server'

        server_name = 'test_create_ssh_exception_server'
        server = cloud_server.CloudServer(server_name,
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(cloud_server.CloudServer, "nova")
        cloud_server.CloudServer.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server._private_key = rsa_key
        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1,
            flavor=1,
            key_name=None,
            name=mox.IgnoreArg(),
            security_groups=[],
            userdata=mox.IgnoreArg(),
            scheduler_hints=None,
            meta=None,
            nics=None,
            availability_zone=None,
            block_device_mapping=None,
            config_drive=None,
            disk_config=None,
            reservation_id=None,
            files=mox.IgnoreArg(),
            admin_pass=None).AndReturn(return_server)

        self.m.StubOutWithMock(cloud_server.CloudServer, 'script')
        cloud_server.CloudServer.script = "foobar"

        transport = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko, "Transport")
        paramiko.Transport((mox.IgnoreArg(), 22)).MultipleTimes().\
            AndReturn(transport)

        # Raise an EOFError the first time
        transport.connect(hostkey=None, username="root",
                          pkey=mox.IgnoreArg()).AndRaise(EOFError)
        transport.connect(hostkey=None, username="root",
                          pkey=mox.IgnoreArg())

        sftp = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko, "SFTPClient")
        paramiko.SFTPClient.from_transport(transport).AndReturn(sftp)
        sftp_file = self.m.CreateMockAnything()
        sftp.open(mox.IgnoreArg(), 'w').MultipleTimes().AndReturn(sftp_file)
        sftp_file.write(mox.IgnoreArg()).MultipleTimes()
        sftp_file.close().MultipleTimes()
        sftp.close()
        transport.close()

        self.m.StubOutWithMock(paramiko, "SSHClient")
        self.m.StubOutWithMock(paramiko, "MissingHostKeyPolicy")
        ssh = self.m.CreateMockAnything()
        paramiko.SSHClient().AndReturn(ssh)
        paramiko.MissingHostKeyPolicy()
        ssh.set_missing_host_key_policy(None)
        ssh.connect(mox.IgnoreArg(),
                    key_filename=mox.IgnoreArg(),
                    username='root')
        fake_chan = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko.SSHClient, "get_transport")
        chan = ssh.get_transport().AndReturn(fake_chan)
        fake_chan_session = self.m.CreateMockAnything()
        chan_session = chan.open_session().AndReturn(fake_chan_session)
        fake_chan_session.settimeout(3600.0)
        chan_session.exec_command(mox.IgnoreArg())
        fake_chan_session.recv(1024)
        chan_session.recv_exit_status().AndReturn(0)
        fake_chan_session.close()
        ssh.close()
        self.m.ReplayAll()

        scheduler.TaskRunner(server.create)()
        self.assertEqual((server.CREATE, server.COMPLETE), server.state)

        self.m.VerifyAll()

    def test_eof_error_failed(self):
        return_server = self.fc.servers.list()[1]
        stack_name = 'test_create_ssh_exception_failed'
        (t, stack) = self._setup_test_stack(stack_name)

        t['Resources']['WebServer']['Properties']['image'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['flavor'] = '256 MB Server'

        server_name = 'test_create_ssh_exception_server'
        server = cloud_server.CloudServer(server_name,
                                          t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(cloud_server.CloudServer, "nova")
        cloud_server.CloudServer.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        server._private_key = rsa_key
        server.t = server.stack.resolve_runtime_data(server.t)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1,
            flavor=1,
            key_name=None,
            name=mox.IgnoreArg(),
            security_groups=[],
            userdata=mox.IgnoreArg(),
            scheduler_hints=None,
            meta=None,
            nics=None,
            availability_zone=None,
            block_device_mapping=None,
            config_drive=None,
            disk_config=None,
            reservation_id=None,
            files=mox.IgnoreArg(),
            admin_pass=None).AndReturn(return_server)

        self.m.StubOutWithMock(cloud_server.CloudServer, 'script')
        cloud_server.CloudServer.script = "foobar"

        transport = self.m.CreateMockAnything()
        self.m.StubOutWithMock(paramiko, "Transport")
        paramiko.Transport((mox.IgnoreArg(), 22)).MultipleTimes().\
            AndReturn(transport)

        # Raise an EOFError every time
        transport.connect(hostkey=None, username="root",
                          pkey=mox.IgnoreArg()).MultipleTimes().\
            AndRaise(EOFError)
        self.m.ReplayAll()

        create = scheduler.TaskRunner(server.create)
        exc = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual("Error: Failed to establish SSH connection after 30 "
                         "tries", str(exc))

        self.m.VerifyAll()
