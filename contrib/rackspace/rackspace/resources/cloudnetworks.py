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

from oslo_log import log as logging
import six

from heat.common.i18n import _
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
        status=support.HIDDEN,
        version='6.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=_('Use OS::Neutron::Net instead.'),
            version='2015.1',
            previous_status=support.SupportStatus(version='2014.1')
        )
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
            required=True,
            constraints=[
                constraints.CustomConstraint('net_cidr')
            ]
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
        self._delete_issued = False

    def network(self):
        if self.resource_id and not self._network:
            try:
                self._network = self.cloud_networks().get(self.resource_id)
            except NotFound:
                LOG.warning("Could not find network %s but resource id is"
                            " set.", self.resource_id)
        return self._network

    def cloud_networks(self):
        return self.client('cloud_networks')

    def handle_create(self):
        cnw = self.cloud_networks().create(label=self.properties[self.LABEL],
                                           cidr=self.properties[self.CIDR])
        self.resource_id_set(cnw.id)

    def handle_check(self):
        self.cloud_networks().get(self.resource_id)

    def check_delete_complete(self, cookie):
        if not self.resource_id:
            return True

        try:
            network = self.cloud_networks().get(self.resource_id)
        except NotFound:
            return True

        if not network:
            return True

        if not self._delete_issued:
            try:
                network.delete()
            except NetworkInUse:
                LOG.warning("Network '%s' still in use.", network.id)
            else:
                self._delete_issued = True
            return False

        return False

    def validate(self):
        super(CloudNetwork, self).validate()

    def _resolve_attribute(self, name):
        net = self.network()
        if net:
            return six.text_type(getattr(net, name))
        return ""


def resource_mapping():
    return {'Rackspace::Cloud::Network': CloudNetwork}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
