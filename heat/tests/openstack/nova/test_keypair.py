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
from heat.engine.clients.os import keystone
from heat.engine.clients.os import nova
from heat.engine import resource
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
        self.fake_nova = mock.MagicMock()
        self.fake_keypairs = mock.MagicMock()
        self.fake_nova.keypairs = self.fake_keypairs
        self.patchobject(nova.NovaClientPlugin, 'has_extension',
                         return_value=True)
        self.cp_mock = self.patchobject(nova.NovaClientPlugin, 'client',
                                        return_value=self.fake_nova)

    def _mock_key(self, name, pub=None, priv=None):
        mkey = mock.MagicMock()
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
        return kp_res

    def _get_mock_kp_for_create(self, key_name, public_key=None,
                                priv_saved=False, key_type=None,
                                user=None):
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
        if key_type:
            props['type'] = key_type
        if user:
            props['user'] = user
        kp_res = self._get_test_resource(template)
        self.patchobject(self.fake_keypairs, 'create',
                         return_value=nova_key)
        return kp_res, nova_key

    def test_create_key(self):
        """Test basic create."""
        key_name = "generate_no_save"
        tp_test, created_key = self._get_mock_kp_for_create(key_name)
        self.patchobject(self.fake_keypairs, 'get', return_value=created_key)
        key_info = {'key_pair': 'info'}
        self.patchobject(created_key, 'to_dict',
                         return_value=key_info)
        scheduler.TaskRunner(tp_test.create)()
        self.fake_keypairs.create.assert_called_once_with(
            name=key_name, public_key=None)
        self.assertEqual("", tp_test.FnGetAtt('private_key'))
        self.assertEqual("generated test public key",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual(key_info, tp_test.FnGetAtt('show'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)

    def test_create_key_with_type(self):
        """Test basic create."""
        key_name = "with_type"
        tp_test, created_key = self._get_mock_kp_for_create(key_name,
                                                            key_type='ssh')
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.fake_keypairs.create.assert_called_once_with(
            name=key_name, public_key=None, type='ssh')
        self.cp_mock.assert_called_once_with()

    def test_create_key_with_user_id(self):
        key_name = "create_with_user_id"
        tp_test, created_key = self._get_mock_kp_for_create(key_name,
                                                            user='userA')
        self.patchobject(keystone.KeystoneClientPlugin, 'get_user_id',
                         return_value='userA_ID')
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.fake_keypairs.create.assert_called_once_with(
            name=key_name, public_key=None, user_id='userA_ID')
        self.cp_mock.assert_called_once_with()

    def test_create_key_with_user_and_type(self):
        key_name = "create_with_user_id_and_type"
        tp_test, created_key = self._get_mock_kp_for_create(key_name,
                                                            user='userA',
                                                            key_type='x509')
        self.patchobject(keystone.KeystoneClientPlugin, 'get_user_id',
                         return_value='userA_ID')
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)
        self.fake_keypairs.create.assert_called_once_with(
            name=key_name, public_key=None, user_id='userA_ID',
            type='x509')
        self.cp_mock.assert_called_once_with()

    def test_create_key_empty_name(self):
        """Test creation of a keypair whose name is of length zero."""
        key_name = ""
        template = copy.deepcopy(self.kp_template)
        template['resources']['kp']['properties']['name'] = key_name
        stack = utils.parse_stack(template)
        definition = stack.t.resource_definitions(stack)['kp']
        kp_res = keypair.KeyPair('kp', definition, stack)
        error = self.assertRaises(exception.StackValidationFailed,
                                  kp_res.validate)
        self.assertIn("Property error", six.text_type(error))
        self.assertIn("kp.properties.name: length (0) is out of "
                      "range (min: 1, max: 255)", six.text_type(error))

    def test_create_key_excess_name_length(self):
        """Test creation of a keypair whose name is of excess length."""
        key_name = 'k' * 256
        template = copy.deepcopy(self.kp_template)
        template['resources']['kp']['properties']['name'] = key_name
        stack = utils.parse_stack(template)
        definition = stack.t.resource_definitions(stack)['kp']
        kp_res = keypair.KeyPair('kp', definition, stack)
        error = self.assertRaises(exception.StackValidationFailed,
                                  kp_res.validate)
        self.assertIn("Property error", six.text_type(error))
        self.assertIn("kp.properties.name: length (256) is out of "
                      "range (min: 1, max: 255)", six.text_type(error))

    def _test_validate(self, key_type=None, user=None):
        template = copy.deepcopy(self.kp_template)
        validate_props = []
        if key_type:
            template['resources']['kp']['properties']['type'] = key_type
            validate_props.append('type')
        if user:
            template['resources']['kp']['properties']['user'] = user
            validate_props.append('user')
        stack = utils.parse_stack(template)
        definition = stack.t.resource_definitions(stack)['kp']
        kp_res = keypair.KeyPair('kp', definition, stack)
        error = self.assertRaises(exception.StackValidationFailed,
                                  kp_res.validate)
        msg = (('Cannot use "%s" properties - nova does not support '
                'required api microversion.') % validate_props)
        self.assertIn(msg, six.text_type(error))

    def test_validate_key_type(self):
        self.patchobject(nova.NovaClientPlugin, 'get_max_microversion',
                         return_value='2.1')
        self._test_validate(key_type='x509')

    def test_validate_user(self):
        self.patchobject(keystone.KeystoneClientPlugin, 'get_user_id',
                         return_value='user_A')
        self.patchobject(nova.NovaClientPlugin, 'get_max_microversion',
                         return_value='2.1')
        self._test_validate(user='user_A')

    def test_check_key(self):
        res = self._get_test_resource(self.kp_template)
        res.state_set(res.CREATE, res.COMPLETE, 'for test')
        res.client = mock.Mock()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_check_key_fail(self):
        res = self._get_test_resource(self.kp_template)
        res.state_set(res.CREATE, res.COMPLETE, 'for test')
        res.client = mock.Mock()
        res.client().keypairs.get.side_effect = Exception("boom")
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.check))
        self.assertIn("boom", six.text_type(exc))
        self.assertEqual((res.CHECK, res.FAILED), res.state)

    def test_update_replace(self):
        res = self._get_test_resource(self.kp_template)
        res.state_set(res.CHECK, res.FAILED, 'for test')
        res.resource_id = 'my_key'
        # to delete the keypair preparing for replace
        self.fake_keypairs.delete('my_key')
        updater = scheduler.TaskRunner(res.update, res.t)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_delete_key_not_found(self):
        """Test delete non-existent key."""
        test_res = self._get_test_resource(self.kp_template)
        test_res.resource_id = "key_name"
        test_res.state_set(test_res.CREATE, test_res.COMPLETE)
        self.patchobject(self.fake_keypairs, 'delete',
                         side_effect=fakes_nova.fake_exception())
        scheduler.TaskRunner(test_res.delete)()
        self.assertEqual((test_res.DELETE, test_res.COMPLETE), test_res.state)

    def test_create_pub(self):
        """Test create using existing pub key."""
        key_name = "existing_key"
        pk = "test_create_pub"
        tp_test, created_key = self._get_mock_kp_for_create(key_name,
                                                            public_key=pk)
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual("", tp_test.FnGetAtt('private_key'))
        self.assertEqual("test_create_pub",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)

    def test_save_priv_key(self):
        """Test a saved private key."""
        key_name = "save_private"
        tp_test, created_key = self._get_mock_kp_for_create(key_name,
                                                            priv_saved=True)
        self.patchobject(self.fake_keypairs, 'get', return_value=created_key)
        scheduler.TaskRunner(tp_test.create)()
        self.assertEqual("private key for save_private",
                         tp_test.FnGetAtt('private_key'))
        self.assertEqual("generated test public key",
                         tp_test.FnGetAtt('public_key'))
        self.assertEqual((tp_test.CREATE, tp_test.COMPLETE), tp_test.state)
        self.assertEqual(tp_test.resource_id, created_key.name)

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
        rsrc = stack.defn['kp']
        self.assertEqual('convg_xyz', rsrc.FnGetRefId())
