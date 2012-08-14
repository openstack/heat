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
import urlparse
import httplib
import routes
import gettext

gettext.install('heat', unicode=1)

from heat.api.v1 import stacks
from heat.common import wsgi

from webob import Request
import webob
from heat import utils
from heat.common import context
from heat.api.v1 import exception

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class EC2Token(wsgi.Middleware):
    """Authenticate an EC2 request with keystone and convert to token."""

    def __init__(self, app, conf):
        self.conf = conf
        self.application = app

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        # Read request signature and access id.
        # If we find KeyStoneCreds in the params we ignore a key error
        # here so that we can use both authentication methods.
        # Returning here just means the user didn't supply AWS
        # authentication and we'll let the app try native keystone next.
        logger.info("Checking AWS credentials..")
        try:
            signature = req.params['Signature']
        except KeyError:
            logger.info("No AWS Signature found.")
            if 'KeyStoneCreds' in req.params:
                return self.application
            else:
                raise exception.HeatIncompleteSignatureError()

        try:
            access = req.params['AWSAccessKeyId']
        except KeyError:
            logger.info("No AWSAccessKeyId found.")
            if 'KeyStoneCreds' in req.params:
                return self.application
            else:
                raise exception.HeatMissingAuthenticationTokenError()

        logger.info("AWS credentials found, checking against keystone.")
        # Make a copy of args for authentication and signature verification.
        auth_params = dict(req.params)
        # Not part of authentication args
        auth_params.pop('Signature')

        # Authenticate the request.
        creds = {'ec2Credentials': {'access': access,
                                    'signature': signature,
                                    'host': req.host,
                                    'verb': req.method,
                                    'path': req.path,
                                    'params': auth_params,
                                   }}
        creds_json = None
        try:
            creds_json = json.dumps(creds)
        except TypeError:
            creds_json = json.dumps(to_primitive(creds))
        headers = {'Content-Type': 'application/json'}

        # Disable 'has no x member' pylint error
        # for httplib and urlparse
        # pylint: disable-msg=E1101

        logger.info('Authenticating with %s' % self.conf['keystone_ec2_uri'])
        o = urlparse.urlparse(self.conf['keystone_ec2_uri'])
        if o.scheme == 'http':
            conn = httplib.HTTPConnection(o.netloc)
        else:
            conn = httplib.HTTPSConnection(o.netloc)
        conn.request('POST', o.path, body=creds_json, headers=headers)
        response = conn.getresponse().read()
        conn.close()

        # NOTE(vish): We could save a call to keystone by
        #             having keystone return token, tenant,
        #             user, and roles from this call.

        result = json.loads(response)
        try:
            token_id = result['access']['token']['id']
            logger.info("AWS authentication successful.")
        except (AttributeError, KeyError):
            logger.info("AWS authentication failure.")
            # Try to extract the reason for failure so we can return the
            # appropriate AWS error via raising an exception
            try:
                reason = result['error']['message']
            except KeyError:
                reason = None

            if reason == "EC2 access key not found.":
                raise exception.HeatInvalidClientTokenIdError()
            elif reason == "EC2 signature not supplied.":
                raise exception.HeatSignatureError()
            else:
                raise exception.HeatAccessDeniedError()

        # Authenticated!
        req.headers['X-Auth-EC2-Creds'] = creds_json
        req.headers['X-Auth-Token'] = token_id
        req.headers['X-Auth-URL'] = self.conf['auth_uri']
        req.headers['X-Auth-EC2_URL'] = self.conf['keystone_ec2_uri']
        return self.application


def EC2Token_filter_factory(global_conf, **local_conf):
    """
    Factory method for paste.deploy
    """
    conf = global_conf.copy()
    conf.update(local_conf)

    def filter(app):
        return EC2Token(app, conf)

    return filter
