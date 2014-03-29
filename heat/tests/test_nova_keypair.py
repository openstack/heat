
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

import collections
import copy

from novaclient import exceptions as nova_exceptions

from heat.engine import clients
from heat.engine.resources import nova_keypair
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


class NovaKeyPairTest(HeatTestCase):

    kp_template = {
        "heat_template_version": "2013-05-23",
        "resources": {
            "kp": {
                "type": "OS::Nova::KeyPair",
                "properties": {
                    "name": "key_pair"
                }
            }
        }
    }

    def setUp(self):
        super(NovaKeyPairTest, self).setUp()
        utils.setup_dummy_db()
        self.fake_nova = self.m.CreateMockAnything()
        self.fake_keypairs = self.m.CreateMockAnything()
        self.fake_nova.keypairs = self.fake_keypairs

    def _mock_key(self, name, pub=None, priv=None):
        mkey = self.m.CreateMockAnything()
        mkey.id = name
        mkey.name = name
        if pub:
            mkey.public_key = pub
        if priv:
            mkey.private_key = priv
        return mkey

    def _get_test_resource(self, template):
        stack = utils.parse_stack(template)
        snippet = stack.t['Resources']['kp']
        kp_res = nova_keypair.KeyPair('kp', snippet, stack)
        self.m.StubOutWithMock(kp_res, "nova")
        kp_res.nova().MultipleTimes().AndReturn(self.fake_nova)
        return kp_res

    def _get_mock_kp_for_create(self, key_name, public_key=None,
                                priv_saved=False):
        template = copy.deepcopy(self.kp_template)
        template['resources']['kp']['properties']['name'] = key_name
        props = template['resources']['kp']['properties']
        if public_key:
            props['public_key'] = public_key
        gen_pk = public_key or "generated test public key"
        nova_key = self._mock_key(key_name, gen_pk)
        if priv_saved:
            nova_key.private_key = "private key for %s" % key_name
            props['save_private_key'] = True
        kp_res = self._get_test_resource(template)
        self.fake_keypairs.create(key_name,
                                  public_key=public_key).AndReturn(nova_key)
        return kp_res, nova_key

    def test_create_key(self):
        """Test basic create."""
        key_name = "generate_no_save"
        tp_test, created_key = self._get_mock_kp_for_create(key_name)
        self.fake_keypairs.list().AndReturn([created_key])
        self.m.ReplayAll()
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual("", tp_test.FnGetAtt('private_key'))
        self.assertEqual("generated test public key",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.m.VerifyAll()

    def test_delete_key(self):
        """Test basic delete."""
        test_res = self._get_test_resource(self.kp_template)
        test_res.resource_id = "key_name"
        test_res.state_set(test_res.CREATE, test_res.COMPLETE)
        self.fake_keypairs.delete("key_name").AndReturn(None)
        self.m.ReplayAll()
        scheduler.TaskRunner(test_res.delete)()
        self.assertEqual((test_res.DELETE, test_res.COMPLETE), test_res.state)
        self.m.VerifyAll()

    def test_delete_key_not_found(self):
        """Test delete non-existant key."""
        test_res = self._get_test_resource(self.kp_template)
        test_res.resource_id = "key_name"
        test_res.state_set(test_res.CREATE, test_res.COMPLETE)
        (self.fake_keypairs.delete("key_name")
            .AndRaise(nova_exceptions.NotFound(404)))
        self.m.ReplayAll()
        scheduler.TaskRunner(test_res.delete)()
        self.assertEqual((test_res.DELETE, test_res.COMPLETE), test_res.state)
        self.m.VerifyAll()

    def test_create_pub(self):
        """Test create using existing pub key."""
        key_name = "existing_key"
        pk = "test_create_pub"
        tp_test, created_key = self._get_mock_kp_for_create(key_name,
                                                            public_key=pk)
        self.m.ReplayAll()
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual("", tp_test.FnGetAtt('private_key'))
        self.assertEqual("test_create_pub",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.m.VerifyAll()

    def test_save_priv_key(self):
        """Test a saved private key."""
        key_name = "save_private"
        tp_test, created_key = self._get_mock_kp_for_create(key_name,
                                                            priv_saved=True)
        self.fake_keypairs.list().AndReturn([created_key])
        self.m.ReplayAll()
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual("private key for save_private",
                         tp_test.FnGetAtt('private_key'))
        self.assertEqual("generated test public key",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.m.VerifyAll()


class KeypairConstraintTest(HeatTestCase):

    def test_validation(self):
        client = fakes.FakeClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(client)
        client.keypairs = self.m.CreateMockAnything()

        key = collections.namedtuple("Key", ["name"])
        key.name = "foo"
        client.keypairs.list().MultipleTimes().AndReturn([key])
        self.m.ReplayAll()

        constraint = nova_keypair.KeypairConstraint()
        self.assertFalse(constraint.validate("bar", None))
        self.assertTrue(constraint.validate("foo", None))
        self.assertTrue(constraint.validate("", None))

        self.m.VerifyAll()
