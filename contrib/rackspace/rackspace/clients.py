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

"""Client Libraries for Rackspace Resources."""

import hashlib
import random
import time

from glanceclient import client as gc
from oslo_config import cfg
from oslo_log import log as logging
from six.moves.urllib import parse
from swiftclient import utils as swiftclient_utils
from troveclient import client as tc

from heat.common import exception
from heat.common.i18n import _LI
from heat.common.i18n import _LW
from heat.engine.clients import client_plugin
from heat.engine.clients.os import cinder
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine.clients.os import swift
from heat.engine.clients.os import trove


LOG = logging.getLogger(__name__)

try:
    import pyrax
except ImportError:
    pyrax = None


class RackspaceClientPlugin(client_plugin.ClientPlugin):

    pyrax = None

    def _get_client(self, name):
        if self.pyrax is None:
            self._authenticate()
        return self.pyrax.get_client(
            name, cfg.CONF.region_name_for_services)

    def _authenticate(self):
        """Create an authenticated client context."""
        self.pyrax = pyrax.create_context("rackspace")
        self.pyrax.auth_endpoint = self.context.auth_url
        LOG.info(_LI("Authenticating username: %s"),
                 self.context.username)
        tenant = self.context.tenant_id
        tenant_name = self.context.tenant
        self.pyrax.auth_with_token(self.context.auth_token,
                                   tenant_id=tenant,
                                   tenant_name=tenant_name)
        if not self.pyrax.authenticated:
            LOG.warn(_LW("Pyrax Authentication Failed."))
            raise exception.AuthorizationFailure()
        LOG.info(_LI("User %s authenticated successfully."),
                 self.context.username)


class RackspaceAutoScaleClient(RackspaceClientPlugin):

    def _create(self):
        """Rackspace Auto Scale client."""
        return self._get_client("autoscale")


class RackspaceCloudLBClient(RackspaceClientPlugin):

    def _create(self):
        """Rackspace cloud loadbalancer client."""
        return self._get_client("load_balancer")


class RackspaceCloudDNSClient(RackspaceClientPlugin):

    def _create(self):
        """Rackspace cloud dns client."""
        return self._get_client("dns")


class RackspaceNovaClient(nova.NovaClientPlugin,
                          RackspaceClientPlugin):

    def _create(self):
        """Rackspace cloudservers client."""
        client = self._get_client("compute")
        if not client:
            client = super(RackspaceNovaClient, self)._create()
        return client


class RackspaceCloudNetworksClient(RackspaceClientPlugin):

    def _create(self):
        """Rackspace cloud networks client.

        Though pyrax "fixed" the network client bugs that were introduced
        in 1.8, it still doesn't work for contexts because of caching of the
        nova client.
        """
        if not self.pyrax:
            self._authenticate()
        # need special handling now since the contextual
        # pyrax doesn't handle "networks" not being in
        # the catalog
        ep = pyrax._get_service_endpoint(
            self.pyrax, "compute", region=cfg.CONF.region_name_for_services)
        cls = pyrax._client_classes['compute:network']
        client = cls(self.pyrax,
                     region_name=cfg.CONF.region_name_for_services,
                     management_url=ep)
        return client


class RackspaceTroveClient(trove.TroveClientPlugin):
    """Rackspace trove client.

    Since the pyrax module uses its own client implementation for Cloud
    Databases, we have to skip pyrax on this one and override the super
    implementation to account for custom service type and regionalized
    management url.
    """

    def _create(self):
        service_type = "rax:database"
        con = self.context
        endpoint_type = self._get_client_option('trove', 'endpoint_type')
        args = {
            'service_type': service_type,
            'auth_url': con.auth_url,
            'proxy_token': con.auth_token,
            'username': None,
            'password': None,
            'cacert': self._get_client_option('trove', 'ca_file'),
            'insecure': self._get_client_option('trove', 'insecure'),
            'endpoint_type': endpoint_type
        }

        client = tc.Client('1.0', **args)
        region = cfg.CONF.region_name_for_services
        management_url = self.url_for(service_type=service_type,
                                      endpoint_type=endpoint_type,
                                      region_name=region)
        client.client.auth_token = con.auth_token
        client.client.management_url = management_url

        return client


class RackspaceCinderClient(cinder.CinderClientPlugin):

    def _create(self):
        """Override the region for the cinder client."""
        client = super(RackspaceCinderClient, self)._create()
        management_url = self.url_for(
            service_type='volume',
            region_name=cfg.CONF.region_name_for_services)
        client.client.management_url = management_url
        return client


class RackspaceSwiftClient(swift.SwiftClientPlugin):

    def is_valid_temp_url_path(self, path):
        """Return True if path is a valid Swift TempURL path, False otherwise.

        A Swift TempURL path must:
        - Be five parts, ['', 'v1', 'account', 'container', 'object']
        - Be a v1 request
        - Have account, container, and object values
        - Have an object value with more than just '/'s

        :param path: The TempURL path
        :type path: string
        """
        parts = path.split('/', 4)
        return bool(len(parts) == 5 and
                    not parts[0] and
                    parts[1] == 'v1' and
                    parts[2] and
                    parts[3] and
                    parts[4].strip('/'))

    def get_temp_url(self, container_name, obj_name, timeout=None,
                     method='PUT'):
        """Return a Swift TempURL."""
        def tenant_uuid():
            access = self.context.auth_token_info['access']
            for role in access['user']['roles']:
                if role['name'] == 'object-store:default':
                    return role['tenantId']

        key_header = 'x-account-meta-temp-url-key'
        if key_header in self.client().head_account():
            key = self.client().head_account()[key_header]
        else:
            key = hashlib.sha224(str(random.getrandbits(256))).hexdigest()[:32]
            self.client().post_account({key_header: key})

        path = '/v1/%s/%s/%s' % (tenant_uuid(), container_name, obj_name)
        if timeout is None:
            timeout = swift.MAX_EPOCH - 60 - time.time()
        tempurl = swiftclient_utils.generate_temp_url(path, timeout, key,
                                                      method)
        sw_url = parse.urlparse(self.client().url)
        return '%s://%s%s' % (sw_url.scheme, sw_url.netloc, tempurl)


class RackspaceGlanceClient(glance.GlanceClientPlugin):

    def _create(self):
        con = self.context
        endpoint_type = self._get_client_option('glance', 'endpoint_type')
        endpoint = self.url_for(
            service_type='image',
            endpoint_type=endpoint_type,
            region_name=cfg.CONF.region_name_for_services)
        # Rackspace service catalog includes a tenant scoped glance
        # endpoint so we have to munge the url a bit
        glance_url = parse.urlparse(endpoint)
        # remove the tenant and following from the url
        endpoint = "%s://%s" % (glance_url.scheme, glance_url.hostname)
        args = {
            'auth_url': con.auth_url,
            'service_type': 'image',
            'project_id': con.tenant,
            'token': self.auth_token,
            'endpoint_type': endpoint_type,
            'ca_file': self._get_client_option('glance', 'ca_file'),
            'cert_file': self._get_client_option('glance', 'cert_file'),
            'key_file': self._get_client_option('glance', 'key_file'),
            'insecure': self._get_client_option('glance', 'insecure')
        }
        return gc.Client('2', endpoint, **args)
