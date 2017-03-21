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

import hashlib

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
import requests
import webob

from heat.api.aws import exception
from heat.common import endpoint_utils
from heat.common.i18n import _
from heat.common import wsgi

LOG = logging.getLogger(__name__)


opts = [
    cfg.StrOpt('auth_uri',
               help=_("Authentication Endpoint URI.")),
    cfg.BoolOpt('multi_cloud',
                default=False,
                help=_('Allow orchestration of multiple clouds.')),
    cfg.ListOpt('allowed_auth_uris',
                default=[],
                help=_('Allowed keystone endpoints for auth_uri when '
                       'multi_cloud is enabled. At least one endpoint needs '
                       'to be specified.')),
    cfg.StrOpt('cert_file',
               help=_('Optional PEM-formatted certificate chain file.')),
    cfg.StrOpt('key_file',
               help=_('Optional PEM-formatted file that contains the '
                      'private key.')),
    cfg.StrOpt('ca_file',
               help=_('Optional CA cert file to use in SSL connections.')),
    cfg.BoolOpt('insecure',
                default=False,
                help=_('If set, then the server\'s certificate will not '
                       'be verified.')),
]
cfg.CONF.register_opts(opts, group='ec2authtoken')


class EC2Token(wsgi.Middleware):
    """Authenticate an EC2 request with keystone and convert to token."""

    def __init__(self, app, conf):
        self.conf = conf
        self.application = app
        self._ssl_options = None

    def _conf_get(self, name):
        # try config from paste-deploy first
        if name in self.conf:
            return self.conf[name]
        else:
            return cfg.CONF.ec2authtoken[name]

    def _conf_get_auth_uri(self):
        auth_uri = self._conf_get('auth_uri')
        if auth_uri:
            return auth_uri.replace('v2.0', 'v3')
        else:
            return endpoint_utils.get_auth_uri()

    @staticmethod
    def _conf_get_keystone_ec2_uri(auth_uri):
        if auth_uri.endswith('ec2tokens'):
            return auth_uri
        if auth_uri.endswith('/'):
            return '%sec2tokens' % auth_uri
        return '%s/ec2tokens' % auth_uri

    def _get_signature(self, req):
        """Extract the signature from the request.

        This can be a get/post variable or for v4 also in a header called
        'Authorization'.

        - params['Signature'] == version 0,1,2,3
        - params['X-Amz-Signature'] == version 4
        - header 'Authorization' == version 4
        """
        sig = req.params.get('Signature') or req.params.get('X-Amz-Signature')
        if sig is None and 'Authorization' in req.headers:
            auth_str = req.headers['Authorization']
            sig = auth_str.partition("Signature=")[2].split(',')[0]

        return sig

    def _get_access(self, req):
        """Extract the access key identifier.

        For v 0/1/2/3 this is passed as the AccessKeyId parameter,
        for version4 it is either and X-Amz-Credential parameter or a
        Credential= field in the 'Authorization' header string.
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
        if not self._conf_get('multi_cloud'):
            return self._authorize(req, self._conf_get_auth_uri())
        else:
            # attempt to authorize for each configured allowed_auth_uris
            # until one is successful.
            # This is safe for the following reasons:
            # 1. AWSAccessKeyId is a randomly generated sequence
            # 2. No secret is transferred to validate a request
            last_failure = None
            for auth_uri in self._conf_get('allowed_auth_uris'):
                try:
                    LOG.debug("Attempt authorize on %s" % auth_uri)
                    return self._authorize(req, auth_uri)
                except exception.HeatAPIException as e:
                    LOG.debug("Authorize failed: %s" % e.__class__)
                    last_failure = e
            raise last_failure or exception.HeatAccessDeniedError()

    @property
    def ssl_options(self):
        if not self._ssl_options:
            cacert = self._conf_get('ca_file')
            insecure = self._conf_get('insecure')
            cert = self._conf_get('cert_file')
            key = self._conf_get('key_file')
            self._ssl_options = {
                'verify': cacert if cacert else not insecure,
                'cert': (cert, key) if cert else None
            }
        return self._ssl_options

    def _authorize(self, req, auth_uri):
        # Read request signature and access id.
        # If we find X-Auth-User in the headers we ignore a key error
        # here so that we can use both authentication methods.
        # Returning here just means the user didn't supply AWS
        # authentication and we'll let the app try native keystone next.
        LOG.info("Checking AWS credentials..")

        signature = self._get_signature(req)
        if not signature:
            if 'X-Auth-User' in req.headers:
                return self.application
            else:
                LOG.info("No AWS Signature found.")
                raise exception.HeatIncompleteSignatureError()

        access = self._get_access(req)
        if not access:
            if 'X-Auth-User' in req.headers:
                return self.application
            else:
                LOG.info("No AWSAccessKeyId/Authorization Credential")
                raise exception.HeatMissingAuthenticationTokenError()

        LOG.info("AWS credentials found, checking against keystone.")

        if not auth_uri:
            LOG.error("Ec2Token authorization failed, no auth_uri "
                      "specified in config file")
            raise exception.HeatInternalFailureError(_('Service '
                                                       'misconfigured'))
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
                                    'headers': dict(req.headers),
                                    'body_hash': body_hash
                                    }}
        creds_json = json.dumps(creds)
        headers = {'Content-Type': 'application/json'}

        keystone_ec2_uri = self._conf_get_keystone_ec2_uri(auth_uri)
        LOG.info('Authenticating with %s', keystone_ec2_uri)
        response = requests.post(keystone_ec2_uri, data=creds_json,
                                 headers=headers,
                                 verify=self.ssl_options['verify'],
                                 cert=self.ssl_options['cert'])
        result = response.json()
        try:
            token_id = response.headers['X-Subject-Token']
            tenant = result['token']['project']['name']
            tenant_id = result['token']['project']['id']
            roles = [role['name']
                     for role in result['token'].get('roles', [])]
        except (AttributeError, KeyError):
            LOG.info("AWS authentication failure.")
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
        else:
            LOG.info("AWS authentication successful.")

        # Authenticated!
        ec2_creds = {'ec2Credentials': {'access': access,
                                        'signature': signature}}
        req.headers['X-Auth-EC2-Creds'] = json.dumps(ec2_creds)
        req.headers['X-Auth-Token'] = token_id
        req.headers['X-Tenant-Name'] = tenant
        req.headers['X-Tenant-Id'] = tenant_id
        req.headers['X-Auth-URL'] = auth_uri

        req.headers['X-Roles'] = ','.join(roles)

        return self.application


def EC2Token_filter_factory(global_conf, **local_conf):
    """Factory method for paste.deploy."""
    conf = global_conf.copy()
    conf.update(local_conf)

    def filter(app):
        return EC2Token(app, conf)

    return filter


def list_opts():
    yield 'ec2authtoken', opts
