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

from keystoneauth1 import exceptions as kc_exceptions
import six

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.resources import stack_user
from heat.engine import scheduler
from heat.objects import resource_data as resource_data_object
from heat.tests import common
from heat.tests import fakes
from heat.tests import utils


user_template = '''
heat_template_version: 2013-05-23

resources:
  user:
    type: StackUserResourceType
'''


class StackUserTest(common.HeatTestCase):

    def setUp(self):
        super(StackUserTest, self).setUp()
        self.fc = fakes.FakeKeystoneClient()

    def _user_create(self, stack_name, project_id, user_id,
                     resource_name='user', create_project=True,
                     password=None):
        t = template_format.parse(user_template)
        self.stack = utils.parse_stack(t, stack_name=stack_name)
        rsrc = self.stack[resource_name]

        self.m.StubOutWithMock(stack_user.StackUser, 'keystone')
        stack_user.StackUser.keystone().MultipleTimes().AndReturn(self.fc)

        if create_project:
            self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                                   'create_stack_domain_project')
            fakes.FakeKeystoneClient.create_stack_domain_project(
                self.stack.id).AndReturn(project_id)
        else:
            self.stack.set_stack_user_project_id(project_id)

        rsrc._store()
        self.m.StubOutWithMock(short_id, 'get_id')
        short_id.get_id(rsrc.uuid).AndReturn('aabbcc')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'create_stack_domain_user')
        expected_username = '%s-%s-%s' % (stack_name, resource_name, 'aabbcc')
        fakes.FakeKeystoneClient.create_stack_domain_user(
            username=expected_username, password=password,
            project_id=project_id).AndReturn(user_id)

        return rsrc

    def test_handle_create_no_stack_project(self):
        rsrc = self._user_create(stack_name='stackuser_crnoprj',
                                 project_id='aproject123',
                                 user_id='auser123')
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': 'auser123'}, rs_data)
        self.m.VerifyAll()

    def test_handle_create_existing_project(self):
        rsrc = self._user_create(stack_name='stackuser_crexistprj',
                                 project_id='aproject456',
                                 user_id='auser456',
                                 create_project=False)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': 'auser456'}, rs_data)
        self.m.VerifyAll()

    def test_handle_delete(self):
        rsrc = self._user_create(stack_name='stackuser_testdel',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'delete_stack_domain_user')
        fakes.FakeKeystoneClient.delete_stack_domain_user(
            user_id='auserdel', project_id='aprojectdel').AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_handle_delete_not_found(self):
        rsrc = self._user_create(stack_name='stackuser_testdel_notfound',
                                 project_id='aprojectdel2',
                                 user_id='auserdel2')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'delete_stack_domain_user')
        fakes.FakeKeystoneClient.delete_stack_domain_user(
            user_id='auserdel2', project_id='aprojectdel2').AndRaise(
                kc_exceptions.NotFound)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_handle_delete_noid(self):
        rsrc = self._user_create(stack_name='stackuser_testdel_noid',
                                 project_id='aprojectdel2',
                                 user_id='auserdel2')

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        resource_data_object.ResourceData.delete(rsrc, 'user_id')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_handle_suspend(self):
        rsrc = self._user_create(stack_name='stackuser_testsusp',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'disable_stack_domain_user')
        fakes.FakeKeystoneClient.disable_stack_domain_user(
            user_id='auserdel', project_id='aprojectdel').AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_handle_suspend_legacy(self):
        rsrc = self._user_create(stack_name='stackuser_testsusp_lgcy',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'disable_stack_domain_user')
        fakes.FakeKeystoneClient.disable_stack_domain_user(
            user_id='auserdel', project_id='aprojectdel').AndRaise(ValueError)
        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'disable_stack_user')
        fakes.FakeKeystoneClient.disable_stack_user(
            user_id='auserdel').AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_handle_resume(self):
        rsrc = self._user_create(stack_name='stackuser_testresume',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'enable_stack_domain_user')
        fakes.FakeKeystoneClient.enable_stack_domain_user(
            user_id='auserdel', project_id='aprojectdel').AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_handle_resume_legacy(self):
        rsrc = self._user_create(stack_name='stackuser_testresume_lgcy',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'enable_stack_domain_user')
        fakes.FakeKeystoneClient.enable_stack_domain_user(
            user_id='auserdel', project_id='aprojectdel').AndRaise(ValueError)
        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'enable_stack_user')
        fakes.FakeKeystoneClient.enable_stack_user(
            user_id='auserdel').AndReturn(None)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_keypair(self):
        rsrc = self._user_create(stack_name='stackuser_test_cr_keypair',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        # create_stack_domain_user_keypair(self, user_id, project_id):
        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'create_stack_domain_user_keypair')
        fakes.FakeKeystoneClient.create_stack_domain_user_keypair(
            user_id='auserdel', project_id='aprojectdel').AndReturn(
                self.fc.creds)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        kp = rsrc._create_keypair()
        self.assertEqual(self.fc.credential_id, kp.id)
        self.assertEqual(self.fc.access, kp.access)
        self.assertEqual(self.fc.secret, kp.secret)
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual(self.fc.credential_id, rs_data['credential_id'])
        self.assertEqual(self.fc.access, rs_data['access_key'])
        self.assertEqual(self.fc.secret, rs_data['secret_key'])
        self.m.VerifyAll()

    def test_create_keypair_error(self):
        rsrc = self._user_create(stack_name='stackuser_test_cr_keypair_err',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        # create_stack_domain_user_keypair(self, user_id, project_id):
        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'create_stack_domain_user_keypair')
        fakes.FakeKeystoneClient.create_stack_domain_user_keypair(
            user_id='auserdel', project_id='aprojectdel').AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertRaises(exception.Error, rsrc._create_keypair)
        self.m.VerifyAll()

    def test_delete_keypair(self):
        rsrc = self._user_create(stack_name='stackuser_testdel_keypair',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'delete_stack_domain_user_keypair')
        fakes.FakeKeystoneClient.delete_stack_domain_user_keypair(
            user_id='auserdel', project_id='aprojectdel',
            credential_id='acredential').AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.data_set('credential_id', 'acredential')
        rsrc.data_set('access_key', 'access123')
        rsrc.data_set('secret_key', 'verysecret')
        rsrc._delete_keypair()
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': 'auserdel'}, rs_data)
        self.m.VerifyAll()

    def test_delete_keypair_no_credential_id(self):
        rsrc = self._user_create(stack_name='stackuser_del_keypair_nocrdid',
                                 project_id='aprojectdel',
                                 user_id='auserdel')
        rsrc._delete_keypair()

    def test_delete_keypair_legacy(self):
        rsrc = self._user_create(stack_name='stackuser_testdel_keypair_lgcy',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'delete_stack_domain_user_keypair')
        fakes.FakeKeystoneClient.delete_stack_domain_user_keypair(
            user_id='auserdel', project_id='aprojectdel',
            credential_id='acredential').AndRaise(ValueError())
        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'delete_ec2_keypair')
        fakes.FakeKeystoneClient.delete_ec2_keypair(
            user_id='auserdel', credential_id='acredential').AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.data_set('credential_id', 'acredential')
        rsrc.data_set('access_key', 'access123')
        rsrc.data_set('secret_key', 'verysecret')
        rsrc._delete_keypair()
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': 'auserdel'}, rs_data)
        self.m.VerifyAll()

    def test_delete_keypair_notfound(self):
        rsrc = self._user_create(stack_name='stackuser_testdel_kpr_notfound',
                                 project_id='aprojectdel',
                                 user_id='auserdel')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'delete_stack_domain_user_keypair')
        fakes.FakeKeystoneClient.delete_stack_domain_user_keypair(
            user_id='auserdel', project_id='aprojectdel',
            credential_id='acredential').AndReturn(None)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.data_set('credential_id', 'acredential')
        rsrc._delete_keypair()
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': 'auserdel'}, rs_data)
        self.m.VerifyAll()

    def test_user_token(self):
        rsrc = self._user_create(stack_name='stackuser_testtoken',
                                 project_id='aproject123',
                                 user_id='aabbcc',
                                 password='apassword')

        self.m.StubOutWithMock(fakes.FakeKeystoneClient,
                               'stack_domain_user_token')
        fakes.FakeKeystoneClient.stack_domain_user_token(
            user_id='aabbcc', project_id='aproject123',
            password='apassword').AndReturn('atoken123')
        self.m.ReplayAll()

        rsrc.password = 'apassword'
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('atoken123', rsrc._user_token())
        self.m.VerifyAll()

    def test_user_token_err_nopassword(self):
        rsrc = self._user_create(stack_name='stackuser_testtoken_err_nopwd',
                                 project_id='aproject123',
                                 user_id='auser123')
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        ex = self.assertRaises(ValueError, rsrc._user_token)
        expected = "Can't get user token without password"
        self.assertEqual(expected, six.text_type(ex))
        self.m.VerifyAll()

    def test_user_token_err_noproject(self):
        stack_name = 'user_token_err_noprohect_stack'
        resource_name = 'user'
        t = template_format.parse(user_template)
        stack = utils.parse_stack(t, stack_name=stack_name)
        rsrc = stack[resource_name]

        ex = self.assertRaises(ValueError, rsrc._user_token)
        expected = "Can't get user token, user not yet created"
        self.assertEqual(expected, six.text_type(ex))
