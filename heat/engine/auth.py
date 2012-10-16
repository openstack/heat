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

import json
import httplib
import urlparse
import base64
from novaclient.v1_1 import client
from novaclient.exceptions import BadRequest
from novaclient.exceptions import NotFound
from novaclient.exceptions import AuthorizationFailure
from heat.common import context
from heat.openstack.common import log as logging

from Crypto.Cipher import AES
from Crypto import Random

from heat.openstack.common import cfg
from heat.openstack.common import importutils


auth_opts = [
    cfg.StrOpt('auth_encryption_key',
               default='notgood',
               help="Encryption key used for authentication info in database")
]

cfg.CONF.register_opts(auth_opts)

logger = logging.getLogger('heat.engine.auth')


def encrypt(auth_info):
    if auth_info is None:
        return None
    iv = Random.new().read(AES.block_size)
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


def authenticate(con, service_type='cloudformation', service_name='heat'):
    """ Authenticate a user context.  This authenticates either an
        EC2 style key context or a keystone user/pass context.

        In the case of EC2 style authentication this will also set the
        username in the context so we can use it to key in the database.
    """

    args = {
        'project_id': con.tenant,
        'auth_url': con.auth_url,
        'service_type': service_type,
        'service_name': service_name,
    }

    if con.password is not None:
        credentials = {
            'username': con.username,
            'api_key': con.password,
        }
    elif con.auth_token is not None:
        credentials = {
            'username': con.service_user,
            'api_key': con.service_password,
            'proxy_token': con.auth_token,
            'proxy_tenant_id': con.tenant_id,
        }
    else:
        # We'll have to do AWS style auth which is more complex.
        # First step is to get a token from the AWS creds.
        headers = {'Content-Type': 'application/json'}

        o = urlparse.urlparse(con.aws_auth_uri)
        if o.scheme == 'http':
            conn = httplib.HTTPConnection(o.netloc)
        else:
            conn = httplib.HTTPSConnection(o.netloc)
        conn.request('POST', o.path, body=con.aws_creds, headers=headers)
        response = conn.getresponse().read()
        conn.close()

        result = json.loads(response)
        try:
            token_id = result['access']['token']['id']
            # We grab the username here because with token auth and EC2
            # we never get it normally.  We could pass it in but then We
            # are relying on user input to give us the correct username.
            # This one is the result of the authentication and is verified.
            username = result['access']['user']['username']
            con.username = username

            logger.info("AWS authentication successful.")
        except (AttributeError, KeyError):
            # FIXME: Should be 404 I think.
            logger.info("AWS authentication failure.")
            raise exception.AuthorizationFailure()

        credentials = {
            'username': con.service_user,
            'api_key': con.service_password,
            'proxy_token': token_id,
            'proxy_tenant_id': con.tenant_id,
        }

    args.update(credentials)
    try:
        # Workaround for issues with python-keyring, need no_cache=True
        # ref https://bugs.launchpad.net/python-novaclient/+bug/1020238
        # TODO(shardy): May be able to remove when the bug above is fixed
        nova = client.Client(no_cache=True, **args)
    except TypeError:
        # for compatibility with essex, which doesn't have no_cache=True
        # TODO(shardy): remove when we no longer support essex
        nova = client.Client(**args)

    nova.authenticate()
    return nova
