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

from cryptography import fernet
from cryptography.hazmat import backends
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import modes
from cryptography.hazmat.primitives import padding
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import encodeutils

from heat.common import exception
from heat.common.i18n import _

auth_opts = [
    cfg.StrOpt('auth_encryption_key',
               secret=True,
               default='notgood but just long enough i t',
               help=_('Key used to encrypt authentication info in the '
                      'database. Length of this key must be 32 characters.'))
]

cfg.CONF.register_opts(auth_opts)


class SymmetricCrypto(object):
    """Symmetric Key Crypto object.

    This class creates a Symmetric Key Crypto object that can be used
    to decrypt arbitrary data.

    Note: This is a reimplementation of the decryption algorithm from
    oslo-incubator, and is provided for backward compatibility. Once we have a
    db migration script available to re-encrypt using new encryption method as
    part of upgrade, this can be removed.

    :param enctype: Encryption Cipher name (default: AES)
    """

    def __init__(self, enctype='AES'):
        self.algo = algorithms.AES

    def decrypt(self, key, msg, b64decode=True):
        """Decrypts the provided ciphertext.

        The ciphertext can be optionally base64 encoded.

        Uses AES-128-CBC with an IV by default.

        :param key: The Encryption key.
        :param msg: the ciphetext, the first block is the IV

        :returns: the plaintext message, after padding is removed.
        """
        key = str.encode(get_valid_encryption_key(key))
        if b64decode:
            msg = base64.b64decode(msg)
        algo = self.algo(key)
        block_size_bytes = algo.block_size // 8
        iv = msg[:block_size_bytes]
        backend = backends.default_backend()
        cipher = Cipher(algo, modes.CBC(iv), backend=backend)
        decryptor = cipher.decryptor()
        padded = (decryptor.update(msg[block_size_bytes:]) +
                  decryptor.finalize())
        unpadder = padding.ANSIX923(algo.block_size).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
        # The original padding algorithm was a slight variation on ANSI X.923,
        # where the size of the padding did not include the byte that tells
        # you the size of the padding. Therefore, we need to remove one extra
        # byte (which will be 0x00) when unpadding.
        return plain[:-1]


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


def encrypted_dict(data, encryption_key=None):
    'Return an encrypted dict. Values converted to json before encrypted'
    return_data = {}
    if not data:
        return return_data
    for prop_name, prop_value in data.items():
        prop_string = jsonutils.dumps(prop_value)
        encrypted_value = encrypt(prop_string, encryption_key)
        return_data[prop_name] = encrypted_value
    return return_data


def decrypted_dict(data, encryption_key=None):
    'Return a decrypted dict. Assume input values are encrypted json fields.'
    return_data = {}
    if not data:
        return return_data
    for prop_name, prop_value in data.items():
        method, value = prop_value
        decrypted_value = decrypt(method, value, encryption_key)
        prop_string = jsonutils.loads(decrypted_value)
        return_data[prop_name] = prop_string
    return return_data


def oslo_decrypt_v1(value, encryption_key=None):
    encryption_key = get_valid_encryption_key(encryption_key)
    sym = SymmetricCrypto()
    return sym.decrypt(encryption_key, value, b64decode=True)


def cryptography_decrypt_v1(value, encryption_key=None):
    encryption_key = get_valid_encryption_key(encryption_key, fix_length=True)
    encoded_key = base64.b64encode(encryption_key.encode('utf-8'))
    sym = fernet.Fernet(encoded_key)
    try:
        return sym.decrypt(encodeutils.safe_encode(value))
    except fernet.InvalidToken:
        raise exception.InvalidEncryptionKey()


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
    encryption_key = str.encode(get_valid_encryption_key(encryption_key))
    auth = base64.b64decode(value)
    AES = algorithms.AES(encryption_key)
    block_size_bytes = AES.block_size // 8
    iv = auth[:block_size_bytes]
    backend = backends.default_backend()
    cipher = Cipher(AES, modes.CFB(iv), backend=backend)
    decryptor = cipher.decryptor()
    return decryptor.update(auth[block_size_bytes:]) + decryptor.finalize()


def list_opts():
    yield None, auth_opts
