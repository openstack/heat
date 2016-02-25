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
