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

import urlparse

from oslo.config import cfg

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine.clients.os import cinder
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine.clients.os import trove

from heat.openstack.common import log as logging

from glanceclient import client as gc
from troveclient import client as tc

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
        LOG.info(_("Authenticating username: %s") %
                 self.context.username)
        tenant = self.context.tenant_id
        tenant_name = self.context.tenant
        self.pyrax.auth_with_token(self.context.auth_token,
                                   tenant_id=tenant,
                                   tenant_name=tenant_name)
        if not self.pyrax.authenticated:
            LOG.warn(_("Pyrax Authentication Failed."))
            raise exception.AuthorizationFailure()
        LOG.info(_("User %s authenticated successfully."),
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
        """
        Rackspace cloud networks client.

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
    """
    Rackspace trove client.

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


class RackspaceSwiftClient(RackspaceClientPlugin):

    def _create(self):
        # Rackspace doesn't include object-store in the default catalog
        # for "reasons". The pyrax client takes care of this, but it
        # returns a wrapper over the upstream python-swiftclient so we
        # unwrap here and things just work
        return self._get_client("object_store").connection


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
        glance_url = urlparse.urlparse(endpoint)
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
