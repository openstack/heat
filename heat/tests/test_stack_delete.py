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

import copy
import time

import fixtures
from keystoneauth1 import exceptions as kc_exceptions
import mock
from oslo_log import log as logging

from heat.common import exception
from heat.common import template_format
from heat.common import timeutils
from heat.engine.clients.os import keystone
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine.clients.os.keystone import heat_keystoneclient as hkc
from heat.engine import scheduler
from heat.engine import stack
from heat.engine import template
from heat.objects import snapshot as snapshot_object
from heat.objects import stack as stack_object
from heat.objects import user_creds as ucreds_object
from heat.tests import common
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

empty_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
}''')


class StackTest(common.HeatTestCase):
    def setUp(self):
        super(StackTest, self).setUp()

        self.tmpl = template.Template(copy.deepcopy(empty_template))
        self.ctx = utils.dummy_context()

    def test_delete(self):
        self.stack = stack.Stack(self.ctx, 'delete_test', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_with_snapshot(self):
        self.stack = stack.Stack(self.ctx, 'delete_test', self.tmpl)
        stack_id = self.stack.store()
        snapshot_fake = {
            'tenant': self.ctx.tenant_id,
            'name': 'Snapshot',
            'stack_id': stack_id,
            'status': 'COMPLETE',
            'data': self.stack.prepare_abandon()
        }
        snapshot_object.Snapshot.create(self.ctx, snapshot_fake)

        self.assertIsNotNone(snapshot_object.Snapshot.get_all(
            self.ctx, stack_id))

        self.stack.delete()
        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual([], snapshot_object.Snapshot.get_all(
            self.ctx, stack_id))

    def test_delete_with_snapshot_after_stack_add_resource(self):
        tpl = {'heat_template_version': 'queens',
               'resources':
                   {'A': {'type': 'ResourceWithRestoreType'}}}
        self.stack = stack.Stack(self.ctx, 'stack_delete_with_snapshot',
                                 template.Template(tpl))
        stack_id = self.stack.store()
        self.stack.create()

        data = copy.deepcopy(self.stack.prepare_abandon())
        data['resources']['A']['resource_data']['a_string'] = 'foo'
        snapshot_fake = {
            'tenant': self.ctx.tenant_id,
            'name': 'Snapshot',
            'stack_id': stack_id,
            'status': 'COMPLETE',
            'data': data
        }
        snapshot_object.Snapshot.create(self.ctx, snapshot_fake)

        self.assertIsNotNone(snapshot_object.Snapshot.get_all(
            self.ctx, stack_id))

        new_tmpl = {'heat_template_version': 'queens',
                    'resources':
                        {'A': {'type': 'ResourceWithRestoreType'},
                         'B': {'type': 'ResourceWithRestoreType'}}}
        updated_stack = stack.Stack(self.ctx, 'update_stack_add_res',
                                    template.Template(new_tmpl))
        self.stack.update(updated_stack)
        self.assertEqual(2, len(self.stack.resources))

        self.stack.delete()
        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual([], snapshot_object.Snapshot.get_all(
            self.ctx, stack_id))

    def test_delete_user_creds(self):
        self.stack = stack.Stack(self.ctx, 'delete_test', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertIsNotNone(db_s.user_creds_id)
        user_creds_id = db_s.user_creds_id
        db_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, db_s.user_creds_id)
        self.assertIsNotNone(db_creds)

        self.stack.delete()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        db_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, user_creds_id)
        self.assertIsNone(db_creds)
        del_db_s = stack_object.Stack.get_by_id(self.ctx,
                                                stack_id,
                                                show_deleted=True)
        self.assertIsNone(del_db_s.user_creds_id)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_user_creds_gone_missing(self):
        '''Do not block stack deletion if user_creds is missing.

        It may happen that user_creds were deleted when a delete operation was
        stopped. We should be resilient to this and still complete the delete
        operation.
        '''
        self.stack = stack.Stack(self.ctx, 'delete_test', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertIsNotNone(db_s.user_creds_id)
        user_creds_id = db_s.user_creds_id
        db_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, db_s.user_creds_id)
        self.assertIsNotNone(db_creds)

        ucreds_object.UserCreds.delete(self.ctx, user_creds_id)

        self.stack.delete()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        db_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, user_creds_id)
        self.assertIsNone(db_creds)
        del_db_s = stack_object.Stack.get_by_id(self.ctx,
                                                stack_id,
                                                show_deleted=True)
        self.assertIsNone(del_db_s.user_creds_id)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_user_creds_fail(self):
        '''Do not stop deleting stacks even failed deleting user_creds.

        It may happen that user_creds were incorrectly saved (truncated) and
        thus cannot be correctly retrieved (and decrypted). In this case,
        stack delete should not be stopped.
        '''
        self.stack = stack.Stack(self.ctx, 'delete_test', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertIsNotNone(db_s.user_creds_id)
        exc = exception.Error('Cannot get user credentials')
        self.patchobject(ucreds_object.UserCreds,
                         'get_by_id').side_effect = exc

        self.stack.delete()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_trust(self):
        self.stub_keystoneclient()

        self.stack = stack.Stack(self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_trust_trustor(self):
        self.stub_keystoneclient(user_id='thetrustor')
        trustor_ctx = utils.dummy_context(user_id='thetrustor')

        self.stack = stack.Stack(trustor_ctx, 'delete_trust_nt', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        user_creds_id = db_s.user_creds_id
        self.assertIsNotNone(user_creds_id)
        user_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, user_creds_id)
        self.assertEqual('thetrustor', user_creds.get('trustor_user_id'))

        self.stack.delete()

        db_s = stack_object.Stack.get_by_id(trustor_ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_trust_not_trustor(self):
        # Stack gets created with trustor_ctx, deleted with other_ctx
        # then the trust delete should be with stored_ctx
        trustor_ctx = utils.dummy_context(user_id='thetrustor')
        other_ctx = utils.dummy_context(user_id='nottrustor')
        stored_ctx = utils.dummy_context(trust_id='thetrust')

        mock_kc = self.patchobject(hkc, 'KeystoneClient')
        self.stub_keystoneclient(user_id='thetrustor')

        mock_sc = self.patchobject(stack.Stack, 'stored_context')
        mock_sc.return_value = stored_ctx

        self.stack = stack.Stack(trustor_ctx, 'delete_trust_nt', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        user_creds_id = db_s.user_creds_id
        self.assertIsNotNone(user_creds_id)
        user_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, user_creds_id)
        self.assertEqual('thetrustor', user_creds.get('trustor_user_id'))

        mock_kc.return_value = fake_ks.FakeKeystoneClient(user_id='nottrustor')

        loaded_stack = stack.Stack.load(other_ctx, self.stack.id)
        loaded_stack.delete()
        mock_sc.assert_called_with()

        db_s = stack_object.Stack.get_by_id(other_ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         loaded_stack.state)

    def test_delete_trust_backup(self):
        class FakeKeystoneClientFail(fake_ks.FakeKeystoneClient):
            def delete_trust(self, trust_id):
                raise Exception("Shouldn't delete")

        mock_kcp = self.patchobject(keystone.KeystoneClientPlugin, '_create',
                                    return_value=FakeKeystoneClientFail())

        self.stack = stack.Stack(self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(backup=True)

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual(self.stack.state,
                         (stack.Stack.DELETE, stack.Stack.COMPLETE))
        mock_kcp.assert_called_once_with()

    def test_delete_trust_nested(self):
        class FakeKeystoneClientFail(fake_ks.FakeKeystoneClient):
            def delete_trust(self, trust_id):
                raise Exception("Shouldn't delete")

        self.stub_keystoneclient(fake_client=FakeKeystoneClientFail())

        self.stack = stack.Stack(self.ctx, 'delete_trust_nested', self.tmpl,
                                 owner_id='owner123')
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        user_creds_id = db_s.user_creds_id
        self.assertIsNotNone(user_creds_id)
        user_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, user_creds_id)
        self.assertIsNotNone(user_creds)

        self.stack.delete()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        user_creds = ucreds_object.UserCreds.get_by_id(
            self.ctx, user_creds_id)
        self.assertIsNotNone(user_creds)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_trust_fail(self):
        class FakeKeystoneClientFail(fake_ks.FakeKeystoneClient):
            def delete_trust(self, trust_id):
                raise kc_exceptions.Forbidden("Denied!")

        mock_kcp = self.patchobject(keystone.KeystoneClientPlugin, '_create',
                                    return_value=FakeKeystoneClientFail())

        self.stack = stack.Stack(self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        mock_kcp.assert_called_with()
        self.assertEqual(2, mock_kcp.call_count)

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_deletes_project(self):
        fkc = fake_ks.FakeKeystoneClient()
        fkc.delete_stack_domain_project = mock.Mock()

        mock_kcp = self.patchobject(keystone.KeystoneClientPlugin, '_create',
                                    return_value=fkc)

        self.stack = stack.Stack(self.ctx, 'delete_trust', self.tmpl)
        stack_id = self.stack.store()

        self.stack.set_stack_user_project_id(project_id='aproject456')

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete()

        mock_kcp.assert_called_with()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        fkc.delete_stack_domain_project.assert_called_once_with(
            project_id='aproject456')

    def test_delete_rollback(self):
        self.stack = stack.Stack(self.ctx, 'delete_rollback_test',
                                 self.tmpl, disable_rollback=False)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(action=self.stack.ROLLBACK)

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNone(db_s)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_delete_badaction(self):
        self.stack = stack.Stack(self.ctx, 'delete_badaction_test', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        self.stack.delete(action="wibble")

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)
        self.assertEqual((stack.Stack.DELETE, stack.Stack.FAILED),
                         self.stack.state)

    def test_stack_delete_timeout(self):
        self.stack = stack.Stack(self.ctx, 'delete_test', self.tmpl)
        stack_id = self.stack.store()

        db_s = stack_object.Stack.get_by_id(self.ctx, stack_id)
        self.assertIsNotNone(db_s)

        def dummy_task():
            while True:
                yield

        start_time = time.time()
        mock_tg = self.patchobject(scheduler.DependencyTaskGroup, '__call__',
                                   return_value=dummy_task())
        mock_wallclock = self.patchobject(timeutils, 'wallclock')
        mock_wallclock.side_effect = [
            start_time,
            start_time + 1,
            start_time + self.stack.timeout_secs() + 1
        ]

        self.stack.delete()

        self.assertEqual((stack.Stack.DELETE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('Delete timed out', self.stack.status_reason)

        mock_tg.assert_called_once_with()
        mock_wallclock.assert_called_with()
        self.assertEqual(3, mock_wallclock.call_count)

    def test_stack_delete_resourcefailure(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        mock_rd = self.patchobject(generic_rsrc.GenericResource,
                                   'handle_delete',
                                   side_effect=Exception('foo'))

        self.stack = stack.Stack(self.ctx, 'delete_test_fail',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.stack.delete()

        mock_rd.assert_called_once_with()
        self.assertEqual((self.stack.DELETE, self.stack.FAILED),
                         self.stack.state)
        self.assertEqual('Resource DELETE failed: Exception: '
                         'resources.AResource: foo',
                         self.stack.status_reason)

    def test_delete_stack_with_resource_log_is_clear(self):
        debug_logger = self.useFixture(
            fixtures.FakeLogger(level=logging.DEBUG,
                                format="%(levelname)8s [%(name)s] "
                                       "%(message)s"))
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        self.stack = stack.Stack(self.ctx, 'delete_log_test',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)
        self.stack.delete()
        self.assertNotIn("destroy from None running",
                         debug_logger.output)

    def test_stack_user_project_id_delete_fail(self):

        class FakeKeystoneClientFail(fake_ks.FakeKeystoneClient):
            def delete_stack_domain_project(self, project_id):
                raise kc_exceptions.Forbidden("Denied!")

        mock_kcp = self.patchobject(keystone.KeystoneClientPlugin, '_create',
                                    return_value=FakeKeystoneClientFail())

        self.stack = stack.Stack(self.ctx, 'user_project_init',
                                 self.tmpl,
                                 stack_user_project_id='aproject1234')
        self.stack.store()
        self.assertEqual('aproject1234', self.stack.stack_user_project_id)
        db_stack = stack_object.Stack.get_by_id(self.ctx, self.stack.id)
        self.assertEqual('aproject1234', db_stack.stack_user_project_id)

        self.stack.delete()

        mock_kcp.assert_called_with()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertIn('Error deleting project', self.stack.status_reason)
