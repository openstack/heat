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
from heat.engine import clients
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

from glanceclient import client as glanceclient

LOG = logging.getLogger(__name__)

try:
    import pyrax
except ImportError:
    LOG.info(_('pyrax not available'))


class Clients(clients.OpenStackClients):

    """Convenience class to create and cache client instances."""

    def __init__(self, context):
        super(Clients, self).__init__(context)
        self.pyrax = None

    def _get_client(self, name):
        if not self.pyrax:
            self.__authenticate()
        if name not in self._clients:
            client = self.pyrax.get_client(
                name, cfg.CONF.region_name_for_services)
            self._clients[name] = client
        return self._clients[name]

    def auto_scale(self):
        """Rackspace Auto Scale client."""
        return self._get_client("autoscale")

    def cloud_lb(self):
        """Rackspace cloud loadbalancer client."""
        return self._get_client("load_balancer")

    def cloud_dns(self):
        """Rackspace cloud dns client."""
        return self._get_client("dns")

    def nova(self):
        """Rackspace cloudservers client."""
        return self._get_client("compute")

    def cloud_networks(self):
        """
        Rackspace cloud networks client.

        Though pyrax "fixed" the network client bugs that were introduced
        in 1.8, it still doesn't work for contexts because of caching of the
        nova client.
        """
        if "networks" not in self._clients:
            if not self.pyrax:
                self.__authenticate()
            # need special handling now since the contextual
            # pyrax doesn't handle "networks" not being in
            # the catalog
            ep = pyrax._get_service_endpoint(
                self.pyrax,
                "compute",
                region=cfg.CONF.region_name_for_services)
            cls = pyrax._client_classes['compute:network']
            self._clients["networks"] = cls(
                self.pyrax,
                region_name=cfg.CONF.region_name_for_services,
                management_url=ep)
        return self._clients["networks"]

    def trove(self):
        """
        Rackspace trove client.

        Since the pyrax module uses its own client implementation for Cloud
        Databases, we have to skip pyrax on this one and override the super
        management url to be region-aware.
        """
        if "trove" not in self._clients:
            super(Clients, self).trove(service_type='rax:database')
            management_url = self.url_for(
                service_type='rax:database',
                region_name=cfg.CONF.region_name_for_services)
            self._clients['trove'].client.management_url = management_url
        return self._clients['trove']

    def cinder(self):
        """Override the region for the cinder client."""
        if "cinder" not in self._clients:
            super(Clients, self).cinder()
            management_url = self.url_for(
                service_type='volume',
                region_name=cfg.CONF.region_name_for_services)
            self._clients['cinder'].client.management_url = management_url
        return self._clients['cinder']

    def swift(self):
        # Rackspace doesn't include object-store in the default catalog
        # for "reasons". The pyrax client takes care of this, but it
        # returns a wrapper over the upstream python-swiftclient so we
        # unwrap here and things just work
        return self._get_client("object_store").connection

    def glance(self):
        if "image" not in self._clients:
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
            client = glanceclient.Client('2', endpoint, **args)
            self._clients["image"] = client
        return self._clients["image"]

    def __authenticate(self):
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
