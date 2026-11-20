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

from heat.common.i18n import _
from heat.engine.resources.openstack.heat import none_resource
from heat.engine import support


class PortPair(none_resource.NoneResource):
    """A resource for neutron networking-sfc port-pair.

    This plug-in requires networking-sfc>=1.0.0. So to enable this
    plug-in, install this library and restart the heat-engine.

    A Port Pair represents a service function instance. The ingress port and
    the egress port of the service function may be specified. If a service
    function has one bidirectional port, the ingress port has the same value
    as the egress port.
    """

    support_status = support.SupportStatus(
        version='28.0.0',
        status=support.HIDDEN,
        message=_('networking-sfc is deprecated'),
        previous_status=support.SupportStatus(
            version='7.0.0',
            status=support.UNSUPPORTED))


def resource_mapping():
    return {
        'OS::Neutron::PortPair': PortPair,
    }
