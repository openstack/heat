# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from Crypto.Cipher import AES
from os import urandom

from oslo.config import cfg

from heat.openstack.common import log as logging


auth_opts = [
    cfg.StrOpt('auth_encryption_key',
               default='notgood but just long enough i think',
               help="Encryption key used for authentication info in database")
]

cfg.CONF.register_opts(auth_opts)

logger = logging.getLogger(__name__)


def encrypt(auth_info):
    if auth_info is None:
        return None
    iv = urandom(AES.block_size)
    cipher = AES.new(cfg.CONF.auth_encryption_key[:32], AES.MODE_CFB, iv)
    res = base64.b64encode(iv + cipher.encrypt(auth_info))
    return res


def decrypt(auth_info):
    if auth_info is None:
        return None
    auth = base64.b64decode(auth_info)
    iv = auth[:AES.block_size]
    cipher = AES.new(cfg.CONF.auth_encryption_key[:32], AES.MODE_CFB, iv)
    res = cipher.decrypt(auth[AES.block_size:])
    return res
