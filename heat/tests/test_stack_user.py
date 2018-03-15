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
import mock
import six

from heat.common import exception
from heat.common import short_id
from heat.common import template_format
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine.resources import stack_user
from heat.engine import scheduler
from heat.objects import resource_data as resource_data_object
from heat.tests import common
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
        self.fc = mock.Mock(spec=fake_ks.FakeKeystoneClient)

    def _user_create(self, stack_name, project_id, user_id,
                     resource_name='user', create_project=True,
                     password=None):
        t = template_format.parse(user_template)
        self.stack = utils.parse_stack(t, stack_name=stack_name)
        rsrc = self.stack[resource_name]
        self.patchobject(stack_user.StackUser, 'keystone',
                         return_value=self.fc)
        if create_project:
            self.fc.create_stack_domain_project.return_value = project_id
        else:
            self.stack.set_stack_user_project_id(project_id)

        rsrc.store()
        mock_get_id = self.patchobject(short_id, 'get_id')
        mock_get_id.return_value = 'aabbcc'

        self.fc.create_stack_domain_user.return_value = user_id
        return rsrc

    def test_handle_create_no_stack_project(self):
        stack_name = 'stackuser_crnoprj'
        resource_name = 'user'
        project_id = 'aproject123'
        user_id = 'auser123'

        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': user_id}, rs_data)
        self.fc.create_stack_domain_project.assert_called_once_with(
            self.stack.id)
        expected_username = '%s-%s-%s' % (stack_name, resource_name, 'aabbcc')
        self.fc.create_stack_domain_user.assert_called_once_with(
            password=None, project_id=project_id, username=expected_username)

    def test_handle_create_existing_project(self):
        stack_name = 'stackuser_crexistprj'
        resource_name = 'user'
        project_id = 'aproject456'
        user_id = 'auser456'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id,
                                 create_project=False)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': user_id}, rs_data)
        self.fc.create_stack_domain_project.assert_not_called()
        expected_username = '%s-%s-%s' % (stack_name, resource_name, 'aabbcc')
        self.fc.create_stack_domain_user.assert_called_once_with(
            password=None, project_id=project_id, username=expected_username)

    def test_handle_delete(self):
        stack_name = 'stackuser_testdel'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.delete_stack_domain_user.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.fc.delete_stack_domain_user.assert_called_once_with(
            user_id=user_id, project_id=project_id)

    def test_handle_delete_not_found(self):
        stack_name = 'stackuser_testdel-notfound'
        project_id = 'aprojectdel2'
        user_id = 'auserdel2'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.delete_stack_domain_user.side_effect = kc_exceptions.NotFound()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.fc.delete_stack_domain_user.assert_called_once_with(
            user_id=user_id, project_id=project_id)

    def test_handle_delete_noid(self):
        stack_name = 'stackuser_testdel-noid'
        project_id = 'aprojectdel2'
        user_id = 'auserdel2'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        resource_data_object.ResourceData.delete(rsrc, 'user_id')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.fc.delete_stack_domain_user.assert_called_once_with(
            user_id=user_id, project_id=project_id)

    def test_handle_suspend(self):
        stack_name = 'stackuser_testsusp'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.disable_stack_domain_user.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)
        self.fc.disable_stack_domain_user.assert_called_once_with(
            user_id=user_id, project_id=project_id)

    def test_handle_suspend_legacy(self):
        stack_name = 'stackuser_testsusp_lgcy'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.disable_stack_domain_user.side_effect = ValueError()
        self.fc.disable_stack_user.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)
        self.fc.disable_stack_domain_user.assert_called_once_with(
            user_id=user_id, project_id=project_id)
        self.fc.disable_stack_user.assert_called_once_with(user_id=user_id)

    def test_handle_resume(self):
        stack_name = 'stackuser_testresume'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.enable_stack_domain_user.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)
        self.fc.enable_stack_domain_user.assert_called_once_with(
            project_id=project_id, user_id=user_id)

    def test_handle_resume_legacy(self):
        stack_name = 'stackuser_testresume_lgcy'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.enable_stack_domain_user.side_effect = ValueError()
        self.fc.enable_stack_user.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)
        self.fc.enable_stack_domain_user.assert_called_once_with(
            user_id=user_id, project_id=project_id)
        self.fc.enable_stack_user.assert_called_once_with(user_id=user_id)

    def test_create_keypair(self):
        stack_name = 'stackuser_test_cr_keypair'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)
        creds = fake_ks.FakeKeystoneClient().creds
        self.fc.creds = creds
        self.fc.credential_id = creds.id
        self.fc.access = creds.access
        self.fc.secret = creds.secret

        # create_stack_domain_user_keypair(self, user_id, project_id):
        self.fc.create_stack_domain_user_keypair.return_value = self.fc.creds

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
        self.fc.create_stack_domain_user_keypair.assert_called_once_with(
            project_id=project_id, user_id=user_id)

    def test_create_keypair_error(self):
        stack_name = 'stackuser_test_cr_keypair-err'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        # create_stack_domain_user_keypair(self, user_id, project_id):
        self.fc.create_stack_domain_user_keypair.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertRaises(exception.Error, rsrc._create_keypair)
        self.fc.create_stack_domain_user_keypair.assert_called_once_with(
            project_id=project_id, user_id=user_id)

    def test_delete_keypair(self):
        stack_name = 'stackuser_testdel_keypair'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.delete_stack_domain_user_keypair.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.data_set('credential_id', 'acredential')
        rsrc.data_set('access_key', 'access123')
        rsrc.data_set('secret_key', 'verysecret')
        rsrc._delete_keypair()
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': user_id}, rs_data)
        self.fc.delete_stack_domain_user_keypair.assert_called_once_with(
            credential_id='acredential', project_id=project_id,
            user_id=user_id)

    def test_delete_keypair_no_credential_id(self):
        stack_name = 'stackuser_testdel_keypair_nocrdid'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        rsrc._delete_keypair()
        self.fc.delete_stack_domain_user_keypair.assert_not_called()

    def test_delete_keypair_legacy(self):
        stack_name = 'stackuser_testdel_keypair_lgcy'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.delete_stack_domain_user_keypair.side_effect = ValueError()
        self.fc.delete_ec2_keypair.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.data_set('credential_id', 'acredential')
        rsrc.data_set('access_key', 'access123')
        rsrc.data_set('secret_key', 'verysecret')
        rsrc._delete_keypair()
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': user_id}, rs_data)
        self.fc.delete_stack_domain_user_keypair.assert_called_once_with(
            credential_id='acredential', project_id=project_id,
            user_id=user_id)
        self.fc.delete_ec2_keypair.assert_called_once_with(
            credential_id='acredential', user_id=user_id)

    def test_delete_keypair_notfound(self):
        stack_name = 'stackuser_testdel_kpr_notfound'
        project_id = 'aprojectdel'
        user_id = 'auserdel'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        self.fc.delete_stack_domain_user_keypair.return_value = None

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.data_set('credential_id', 'acredential')
        rsrc._delete_keypair()
        rs_data = resource_data_object.ResourceData.get_all(rsrc)
        self.assertEqual({'user_id': user_id}, rs_data)
        self.fc.delete_stack_domain_user_keypair.assert_called_once_with(
            credential_id='acredential', project_id=project_id,
            user_id=user_id)

    def test_user_token(self):
        stack_name = 'stackuser_testtoken'
        project_id = 'aproject123'
        user_id = 'aaabbcc'
        password = 'apassword'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id,
                                 password=password)

        self.fc.stack_domain_user_token.return_value = 'atoken123'

        rsrc.password = password
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('atoken123', rsrc._user_token())
        self.fc.stack_domain_user_token.assert_called_once_with(
            password=password, project_id=project_id,
            user_id=user_id)

    def test_user_token_err_nopassword(self):
        stack_name = 'stackuser_testtoken_err_nopwd'
        project_id = 'aproject123'
        user_id = 'auser123'
        rsrc = self._user_create(stack_name=stack_name,
                                 project_id=project_id,
                                 user_id=user_id)

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        ex = self.assertRaises(ValueError, rsrc._user_token)
        expected = "Can't get user token without password"
        self.assertEqual(expected, six.text_type(ex))
        self.fc.stack_domain_user_token.assert_not_called()

    def test_user_token_err_noproject(self):
        stack_name = 'user_token_err_noprohect_stack'
        resource_name = 'user'
        t = template_format.parse(user_template)
        stack = utils.parse_stack(t, stack_name=stack_name)
        rsrc = stack[resource_name]

        ex = self.assertRaises(ValueError, rsrc._user_token)
        expected = "Can't get user token, user not yet created"
        self.assertEqual(expected, six.text_type(ex))
