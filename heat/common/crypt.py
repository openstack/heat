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

import base64
import sys

from Crypto.Cipher import AES
from cryptography import fernet
from oslo_config import cfg
from oslo_utils import encodeutils

from heat.common.i18n import _
from heat.openstack.common.crypto import utils

auth_opts = [
    cfg.StrOpt('auth_encryption_key',
               secret=True,
               default='notgood but just long enough i t',
               help=_('Key used to encrypt authentication info in the '
                      'database. Length of this key must be 32 characters.'))
]

cfg.CONF.register_opts(auth_opts)


def encrypt(value, encryption_key=None):
    if value is None:
        return None, None
    encryption_key = get_valid_encryption_key(encryption_key, fix_length=True)
    encoded_key = base64.b64encode(encryption_key.encode('utf-8'))
    sym = fernet.Fernet(encoded_key)
    res = sym.encrypt(encodeutils.safe_encode(value))
    return 'cryptography_decrypt_v1', encodeutils.safe_decode(res)


def decrypt(method, data, encryption_key=None):
    if method is None or data is None:
        return None
    decryptor = getattr(sys.modules[__name__], method)
    value = decryptor(data, encryption_key)
    if value is not None:
        return encodeutils.safe_decode(value, 'utf-8')


def oslo_decrypt_v1(value, encryption_key=None):
    encryption_key = get_valid_encryption_key(encryption_key)
    sym = utils.SymmetricCrypto()
    return sym.decrypt(encryption_key,
                       value, b64decode=True)


def cryptography_decrypt_v1(value, encryption_key=None):
    encryption_key = get_valid_encryption_key(encryption_key, fix_length=True)
    encoded_key = base64.b64encode(encryption_key.encode('utf-8'))
    sym = fernet.Fernet(encoded_key)
    return sym.decrypt(encodeutils.safe_encode(value))


def get_valid_encryption_key(encryption_key, fix_length=False):
    if encryption_key is None:
        encryption_key = cfg.CONF.auth_encryption_key

    if fix_length and len(encryption_key) < 32:
        # Backward compatible size
        encryption_key = encryption_key * 2

    return encryption_key[:32]


def heat_decrypt(value, encryption_key=None):
    """Decrypt data that has been encrypted using an older version of Heat.

    Note: the encrypt function returns the function that is needed to
    decrypt the data. The database then stores this. When the data is
    then retrieved (potentially by a later version of Heat) the decrypt
    function must still exist. So whilst it may seem that this function
    is not referenced, it will be referenced from the database.
    """
    encryption_key = get_valid_encryption_key(encryption_key)
    auth = base64.b64decode(value)
    iv = auth[:AES.block_size]
    cipher = AES.new(encryption_key, AES.MODE_CFB, iv)
    res = cipher.decrypt(auth[AES.block_size:])
    return res


def list_opts():
    yield None, auth_opts
