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
import itertools

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
import webob

from keystoneauth1 import exceptions as ks_exceptions
from keystoneauth1 import loading as ks_loading

from heat.api.aws import exception
from heat.common.i18n import _
from heat.common import wsgi

LOG = logging.getLogger(__name__)


opts = [
    cfg.BoolOpt('multi_cloud',
                default=False,
                help=_('Allow orchestration of multiple clouds.')),
    cfg.ListOpt('clouds',
                default=[],
                help=_('A list of names of clouds when multicloud is enabled. '
                       'At least one should be defined when multi_cloud is '
                       'enabled. For each name there must be a section '
                       '[ec2authtoken.<name>] with keystone auth settings.')),
]

cfg.CONF.register_opts(opts, group='ec2authtoken')
ks_loading.register_auth_conf_options(cfg.CONF, 'ec2authtoken')
ks_loading.register_session_conf_options(cfg.CONF, 'ec2authtoken')
ks_loading.register_adapter_conf_options(cfg.CONF, 'ec2authtoken')
cfg.CONF.set_default('service_type', 'identity', group='ec2authtoken')


class EC2Token(wsgi.Middleware):
    """Authenticate an EC2 request with keystone and convert to token."""

    def __init__(self, app, conf):
        self.conf = conf
        self.application = app
        self._ks_adapters = self._create_keystone_adapters()

    def _register_ks_opts(self, cfg_group):
        ks_loading.register_auth_conf_options(cfg.CONF, cfg_group)
        ks_loading.register_session_conf_options(cfg.CONF, cfg_group)
        ks_loading.register_adapter_conf_options(cfg.CONF, cfg_group)
        cfg.CONF.set_default('service_type', 'identity', group=cfg_group)

    def _create_ks_adapter(self, cfg_group):
        auth = ks_loading.load_auth_from_conf_options(
            cfg.CONF, cfg_group)
        session = ks_loading.load_session_from_conf_options(
            cfg.CONF, cfg_group, auth=auth)
        return ks_loading.load_adapter_from_conf_options(
            cfg.CONF, cfg_group, session=session)

    def _create_keystone_adapters(self):
        # Create a keystone adapters for each cloud to make requests
        # against the v3/ec2token endpoint.
        ks_adapters = {}
        if self._conf_get('multi_cloud'):
            clouds = self._conf_get('clouds')
            # match each clouds value with an ec2authtoken.<value> section.
            for cloud in clouds:
                cfg_group = f'ec2authtoken.{cloud}'
                self._register_ks_opts(cfg_group)
                ks_adapters[cloud] = self._create_ks_adapter(cfg_group)
        else:
            adapter = self._create_ks_adapter('ec2authtoken')
            ks_adapters[None] = adapter

        return ks_adapters

    def _conf_get(self, name):
        # try config from paste-deploy first
        if name in self.conf:
            return self.conf[name]
        else:
            return cfg.CONF.ec2authtoken[name]

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
            return self._authorize(req, None)
        else:
            # attempt to authorize for each configured cloud until one is
            # successful.
            # This is safe for the following reasons:
            # 1. AWSAccessKeyId is a randomly generated sequence
            # 2. No secret is transferred to validate a request
            last_failure = None
            clouds = self._conf_get('clouds')

            for cloud in clouds:
                try:
                    LOG.debug("Attempt authorize on %s", cloud)
                    return self._authorize(req, cloud)
                except exception.HeatAPIException as e:
                    LOG.debug("Authorize failed: %s", e.__class__)
                    last_failure = e

            raise last_failure or exception.HeatAccessDeniedError()

    def _authorize(self, req, cloud):
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
        adapter = self._ks_adapters.get(cloud)
        if not adapter:
            LOG.error("Ec2Token authorization failed due to missing "
                      "keystone auth configuration for %s", cloud)
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

        keystone_uri = adapter.get_endpoint()
        keystone_ec2_uri = keystone_uri + '/v3/ec2tokens'
        LOG.info('Authenticating with %s', keystone_ec2_uri)
        LOG.debug('Sending ec2tokens API request to %s using auth plugin %s',
                  cloud, adapter.session.auth)
        try:
            response = adapter.post(keystone_ec2_uri, data=creds_json,
                                    headers=headers)
            result = response.json()
            token_id = response.headers['X-Subject-Token']
            tenant = result['token']['project']['name']
            tenant_id = result['token']['project']['id']
            roles = [role['name']
                     for role in result['token'].get('roles', [])]
        except ks_exceptions.Unauthorized:
            LOG.error("Failed to obtain a Keystone token from %s", cloud)
            raise exception.HeatAccessDeniedError()
        except (AttributeError, KeyError):
            LOG.info("AWS authentication failure.")
            # Try to extract the reason for failure so we can return the
            # appropriate AWS error via raising an exception
            try:
                reason = result['error']['message']
            except KeyError:
                reason = None
            # Keystone will return a 401 request for each of the following
            # reasons so we have to check the error message
            if reason == "EC2 access key not found.":
                raise exception.HeatInvalidClientTokenIdError()
            elif reason == "EC2 signature not supplied.":
                raise exception.HeatSignatureError()

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
        req.headers['X-Auth-URL'] = keystone_uri

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
    yield 'ec2authtoken', itertools.chain(
        opts,
        ks_loading.get_auth_common_conf_options(),
        ks_loading.get_auth_plugin_conf_options('v3password'),
        ks_loading.get_session_conf_options(),
        ks_loading.get_adapter_conf_options()
    )
