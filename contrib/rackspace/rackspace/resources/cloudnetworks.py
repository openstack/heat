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

import netaddr
from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LW
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

try:
    from pyrax.exceptions import NetworkInUse  # noqa
    from pyrax.exceptions import NotFound  # noqa
    PYRAX_INSTALLED = True
except ImportError:
    PYRAX_INSTALLED = False

    class NotFound(Exception):
        """Dummy pyrax exception - only used for testing."""

    class NetworkInUse(Exception):
        """Dummy pyrax exception - only used for testing."""


LOG = logging.getLogger(__name__)


class CloudNetwork(resource.Resource):
    """A resource for creating Rackspace Cloud Networks.

    See http://www.rackspace.com/cloud/networks/ for service
    documentation.
    """

    support_status = support.SupportStatus(
        support.DEPRECATED,
        _('Use OS::Neutron::Net instead.'),
    )

    PROPERTIES = (
        LABEL, CIDR
    ) = (
        "label", "cidr"
    )

    ATTRIBUTES = (
        CIDR_ATTR, LABEL_ATTR,
    ) = (
        'cidr', 'label',
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
        CIDR_ATTR: attributes.Schema(
            _("The CIDR for an isolated private network.")
        ),
        LABEL_ATTR: attributes.Schema(
            _("The name of the network.")
        ),
    }

    def __init__(self, name, json_snippet, stack):
        resource.Resource.__init__(self, name, json_snippet, stack)
        self._network = None

    def network(self):
        if self.resource_id and not self._network:
            try:
                self._network = self.cloud_networks().get(self.resource_id)
            except NotFound:
                LOG.warn(_LW("Could not find network %s but resource id is"
                             " set."), self.resource_id)
        return self._network

    def cloud_networks(self):
        return self.client('cloud_networks')

    def handle_create(self):
        cnw = self.cloud_networks().create(label=self.properties[self.LABEL],
                                           cidr=self.properties[self.CIDR])
        self.resource_id_set(cnw.id)

    def handle_check(self):
        self.cloud_networks().get(self.resource_id)

    def handle_delete(self):
        '''Delete cloud network.

        Cloud Network doesn't have a status attribute, and there is a non-zero
        window between the deletion of a server and the acknowledgement from
        the cloud network that it's no longer in use, so it needs some way to
        keep track of when the delete call was successfully issued.
        '''
        network_info = {
            'delete_issued': False,
            'network': self.network(),
        }
        return network_info

    def check_delete_complete(self, network_info):
        network = network_info['network']

        if not network:
            return True

        if not network_info['delete_issued']:
            try:
                network.delete()
            except NetworkInUse:
                LOG.warn("Network '%s' still in use." % network.id)
            else:
                network_info['delete_issued'] = True
            return False

        try:
            network.get()
        except NotFound:
            return True

        return False

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


def resource_mapping():
    return {'Rackspace::Cloud::Network': CloudNetwork}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
