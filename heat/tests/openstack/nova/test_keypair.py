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

import mock
import six

from heat.common import exception
from heat.engine.clients.os import nova
from heat.engine.resources.openstack.nova import keypair
from heat.engine import scheduler
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


class NovaKeyPairTest(common.HeatTestCase):

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
        self.fake_nova = self.m.CreateMockAnything()
        self.fake_keypairs = self.m.CreateMockAnything()
        self.fake_nova.keypairs = self.fake_keypairs
        self.patchobject(nova.NovaClientPlugin, 'has_extension',
                         return_value=True)

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
        self.stack = utils.parse_stack(template)
        definition = self.stack.t.resource_definitions(self.stack)['kp']
        kp_res = keypair.KeyPair('kp', definition, self.stack)
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fake_nova)
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
        self.fake_keypairs.get(key_name).MultipleTimes().AndReturn(created_key)
        created_key.to_dict().AndReturn({'key_pair': 'info'})
        self.m.ReplayAll()
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual("", tp_test.FnGetAtt('private_key'))
        self.assertEqual("generated test public key",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual({'key_pair': 'info'}, tp_test.FnGetAtt('show'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.m.VerifyAll()

    def test_create_key_empty_name(self):
        """Test creation of a keypair whose name is of length zero."""
        key_name = ""
        template = copy.deepcopy(self.kp_template)
        template['resources']['kp']['properties']['name'] = key_name
        stack = utils.parse_stack(template)
        definition = stack.t.resource_definitions(stack)['kp']
        kp_res = keypair.KeyPair('kp', definition, stack)
        self.m.ReplayAll()
        error = self.assertRaises(exception.StackValidationFailed,
                                  kp_res.validate)
        self.assertIn("Property error", six.text_type(error))
        self.assertIn("kp.properties.name: length (0) is out of "
                      "range (min: 1, max: 255)", six.text_type(error))
        self.m.VerifyAll()

    def test_create_key_excess_name_length(self):
        """Test creation of a keypair whose name is of excess length."""
        key_name = 'k' * 256
        template = copy.deepcopy(self.kp_template)
        template['resources']['kp']['properties']['name'] = key_name
        stack = utils.parse_stack(template)
        definition = stack.t.resource_definitions(stack)['kp']
        kp_res = keypair.KeyPair('kp', definition, stack)
        self.m.ReplayAll()
        error = self.assertRaises(exception.StackValidationFailed,
                                  kp_res.validate)
        self.assertIn("Property error", six.text_type(error))
        self.assertIn("kp.properties.name: length (256) is out of "
                      "range (min: 1, max: 255)", six.text_type(error))
        self.m.VerifyAll()

    def test_check_key(self):
        res = self._get_test_resource(self.kp_template)
        res.client = mock.Mock()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_check_key_fail(self):
        res = self._get_test_resource(self.kp_template)
        res.client = mock.Mock()
        res.client().keypairs.get.side_effect = Exception("boom")
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.check))
        self.assertIn("boom", six.text_type(exc))
        self.assertEqual((res.CHECK, res.FAILED), res.state)

    def test_delete_key_not_found(self):
        """Test delete non-existent key."""
        test_res = self._get_test_resource(self.kp_template)
        test_res.resource_id = "key_name"
        test_res.state_set(test_res.CREATE, test_res.COMPLETE)
        (self.fake_keypairs.delete("key_name")
            .AndRaise(fakes_nova.fake_exception()))
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
        self.fake_keypairs.get(key_name).AndReturn(created_key)
        self.m.ReplayAll()
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual("private key for save_private",
                         tp_test.FnGetAtt('private_key'))
        self.assertEqual("generated test public key",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.m.VerifyAll()

    def test_nova_keypair_refid(self):
        stack = utils.parse_stack(self.kp_template)
        rsrc = stack['kp']
        rsrc.resource_id = 'xyz'
        self.assertEqual('xyz', rsrc.FnGetRefId())

    def test_nova_keypair_refid_convergence_cache_data(self):
        cache_data = {'kp': {
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'convg_xyz'
        }}
        stack = utils.parse_stack(self.kp_template, cache_data=cache_data)
        rsrc = stack['kp']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())
