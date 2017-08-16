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

from oslo_config import cfg
import six

from heat.common import config
from heat.common import crypt
from heat.common import exception
from heat.tests import common


class CryptTest(common.HeatTestCase):

    def test_fernet_key(self):
        key = 'x' * 16
        method, result = crypt.encrypt('foo', key)
        self.assertEqual('cryptography_decrypt_v1', method)
        self.assertIsNotNone(result)

    def test_init_auth_encryption_key_length(self):
        """Test for length of the auth_encryption_length in config file"""
        cfg.CONF.set_override('auth_encryption_key', 'abcdefghijklma')
        err = self.assertRaises(exception.Error,
                                config.startup_sanity_check)
        exp_msg = ('heat.conf misconfigured, auth_encryption_key '
                   'must be 32 characters')
        self.assertIn(exp_msg, six.text_type(err))

    def _test_encrypt_decrypt_dict(self, encryption_key=None):
        data = {'p1': u'happy',
                '2': [u'a', u'little', u'blue'],
                'p3': {u'really': u'exited', u'ok int': 9},
                '4': u'',
                'p5': True,
                '6': 7}
        encrypted_data = crypt.encrypted_dict(data, encryption_key)
        for k in encrypted_data:
            self.assertEqual('cryptography_decrypt_v1',
                             encrypted_data[k][0])
            self.assertEqual(2, len(encrypted_data[k]))
        # the keys remain the same
        self.assertEqual(set(data), set(encrypted_data))

        decrypted_data = crypt.decrypted_dict(encrypted_data, encryption_key)
        self.assertEqual(data, decrypted_data)

    def test_encrypt_decrypt_dict_custom_enc_key(self):
        self._test_encrypt_decrypt_dict('just for testing not so great re')

    def test_encrypt_decrypt_dict_default_enc_key(self):
        self._test_encrypt_decrypt_dict()

    def test_decrypt_dict_invalid_key(self):
        data = {'p1': u'happy',
                '2': [u'a', u'little', u'blue'],
                '6': 7}
        encrypted_data = crypt.encrypted_dict(
            data, '767c3ed056cbaa3b9dfedb8c6f825bf0')
        ex = self.assertRaises(exception.InvalidEncryptionKey,
                               crypt.decrypted_dict,
                               encrypted_data,
                               '767c3ed056cbaa3b9dfedb8c6f825bf1')
        self.assertEqual('Can not decrypt data with the auth_encryption_key '
                         'in heat config.',
                         six.text_type(ex))
