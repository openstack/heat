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

DEPR_MSG = _('Neutron LBaaS v1 is deprecated in the Liberty release '
             'and is planned to be removed in a future release. '
             'Going forward, the LBaaS V2 should be used.')


class HealthMonitor(none_resource.NoneResource):
    """A resource for managing health monitors for loadbalancers in Neutron.

    A health monitor is used to determine whether or not back-end members of
    the VIP's pool are usable for processing a request. A pool can have several
    health monitors associated with it. There are different types of health
    monitors supported by the OpenStack LBaaS service:

      - PING: used to ping the members using ICMP.
      - TCP: used to connect to the members using TCP.
      - HTTP: used to send an HTTP request to the member.
      - HTTPS: used to send a secure HTTP request to the member.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0'
        )
    )


class Pool(none_resource.NoneResource):
    """A resource for managing load balancer pools in Neutron.

    A load balancing pool is a logical set of devices, such as web servers,
    that you group together to receive and process traffic. The loadbalancing
    function chooses a member of the pool according to the configured load
    balancing method to handle the new requests or connections received on the
    VIP address. There is only one pool for a VIP.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0'
        )
    )


class PoolMember(none_resource.NoneResource):
    """A resource to handle loadbalancer members.

    A pool member represents the application running on backend server.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0',
            previous_status=support.SupportStatus(version='2014.1')
        )
    )


class LoadBalancer(none_resource.NoneResource):
    """A resource to link a neutron pool with servers.

    A loadbalancer allows linking a neutron pool with specified servers to some
    port.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='9.0.0',
        message=_('Use LBaaS V2 instead.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=DEPR_MSG,
            version='7.0.0',
            previous_status=support.SupportStatus(version='2014.1')
        )
    )


def resource_mapping():
    return {
        'OS::Neutron::HealthMonitor': HealthMonitor,
        'OS::Neutron::Pool': Pool,
        'OS::Neutron::PoolMember': PoolMember,
        'OS::Neutron::LoadBalancer': LoadBalancer,
    }
