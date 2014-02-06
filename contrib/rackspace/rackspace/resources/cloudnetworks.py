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

import netaddr

from heat.common import exception
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

try:
    from pyrax.exceptions import NotFound  # noqa
except ImportError:

    class NotFound(Exception):
        """Dummy pyrax exception - only used for testing."""

    def resource_mapping():
        return {}
else:

    def resource_mapping():
        return {'Rackspace::Cloud::Network': CloudNetwork}

logger = logging.getLogger(__name__)


class CloudNetwork(resource.Resource):
    """
    A resource for creating Rackspace Cloud Networks.

    See http://www.rackspace.com/cloud/networks/ for service
    documentation.
    """

    PROPERTIES = (
        LABEL, CIDR
    ) = (
        "label", "cidr"
    )

    properties_schema = {
        LABEL: properties.Schema(
            properties.Schema.STRING,
            _("The name of the network."),
            required=True,
            constraints=[
                constraints.Length(min=3, max=64)
            ]
        ),
        CIDR: properties.Schema(
            properties.Schema.STRING,
            _("The IP block from which to allocate the network. For example, "
              "172.16.0.0/24 or 2001:DB8::/64."),
            required=True
        )
    }

    attributes_schema = {
        "cidr": _("The CIDR for an isolated private network."),
        "label": _("The name of the network.")
    }

    def __init__(self, name, json_snippet, stack):
        resource.Resource.__init__(self, name, json_snippet, stack)
        self._network = None

    def network(self):
        if self.resource_id and not self._network:
            try:
                self._network = self.cloud_networks().get(self.resource_id)
            except NotFound:
                logger.warn(_("Could not find network %s but resource id "
                              "is set.") % self.resource_id)
        return self._network

    def cloud_networks(self):
        return self.stack.clients.cloud_networks()

    def handle_create(self):
        cnw = self.cloud_networks().create(label=self.properties[self.LABEL],
                                           cidr=self.properties[self.CIDR])
        self.resource_id_set(cnw.id)

    def handle_delete(self):
        net = self.network()
        if net:
            net.delete()
        return net

    def check_delete_complete(self, network):
        if network:
            try:
                network.get()
            except NotFound:
                return True
            else:
                return False
        return True

    def validate(self):
        super(CloudNetwork, self).validate()
        try:
            netaddr.IPNetwork(self.properties[self.CIDR])
        except netaddr.core.AddrFormatError:
            raise exception.StackValidationFailed(message=_("Invalid cidr"))

    def _resolve_attribute(self, name):
        net = self.network()
        if net:
            return unicode(getattr(net, name))
        return ""
