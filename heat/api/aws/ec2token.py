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

import urlparse
import httplib
import gettext
import hashlib

gettext.install('heat', unicode=1)

from heat.common import wsgi
from heat.openstack.common import jsonutils as json

import webob
from heat.api.aws import exception

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class EC2Token(wsgi.Middleware):
    """Authenticate an EC2 request with keystone and convert to token."""

    def __init__(self, app, conf):
        self.conf = conf
        self.application = app

    def _get_signature(self, req):
        """
        Extract the signature from the request, this can be a get/post
        variable or for v4 also in a header called 'Authorization'
        - params['Signature'] == version 0,1,2,3
        - params['X-Amz-Signature'] == version 4
        - header 'Authorization' == version 4
        see http://docs.aws.amazon.com/general/latest/gr/
            sigv4-signed-request-examples.html
        """
        sig = req.params.get('Signature') or req.params.get('X-Amz-Signature')
        if sig is None and 'Authorization' in req.headers:
            auth_str = req.headers['Authorization']
            sig = auth_str.partition("Signature=")[2].split(',')[0]

        return sig

    def _get_access(self, req):
        """
        Extract the access key identifier, for v 0/1/2/3 this is passed
        as the AccessKeyId parameter, for version4 it is either and
        X-Amz-Credential parameter or a Credential= field in the
        'Authorization' header string
        """
        access = req.params.get('AWSAccessKeyId')
        if access is None:
            cred_param = req.params.get('X-Amz-Credential')
            if cred_param:
                access = cred_param.split("/")[0]

        if access is None and 'Authorization' in req.headers:
            auth_str = req.headers['Authorization']
            cred_str = auth_str.partition("Credential=")[2].split(',')[0]
            access = cred_str.split("/")[0]

        return access

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        # Read request signature and access id.
        # If we find X-Auth-User in the headers we ignore a key error
        # here so that we can use both authentication methods.
        # Returning here just means the user didn't supply AWS
        # authentication and we'll let the app try native keystone next.
        logger.info("Checking AWS credentials..")

        signature = self._get_signature(req)
        if not signature:
            if 'X-Auth-User' in req.headers:
                return self.application
            else:
                logger.info("No AWS Signature found.")
                raise exception.HeatIncompleteSignatureError()

        access = self._get_access(req)
        if not access:
            if 'X-Auth-User' in req.headers:
                return self.application
            else:
                logger.info("No AWSAccessKeyId/Authorization Credential")
                raise exception.HeatMissingAuthenticationTokenError()

        logger.info("AWS credentials found, checking against keystone.")
        # Make a copy of args for authentication and signature verification.
        auth_params = dict(req.params)
        # 'Signature' param Not part of authentication args
        auth_params.pop('Signature', None)

        # Authenticate the request.
        # AWS v4 authentication requires a hash of the body
        body_hash = hashlib.sha256(req.body).hexdigest()
        creds = {'ec2Credentials': {'access': access,
                                    'signature': signature,
                                    'host': req.host,
                                    'verb': req.method,
                                    'path': req.path,
                                    'params': auth_params,
                                    'headers': req.headers,
                                    'body_hash': body_hash
                                    }}
        creds_json = None
        try:
            creds_json = json.dumps(creds)
        except TypeError:
            creds_json = json.dumps(json.to_primitive(creds))
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
        ec2_creds = {'ec2Credentials': {'access': access,
                                        'signature': signature}}
        req.headers['X-Auth-EC2-Creds'] = json.dumps(ec2_creds)
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
