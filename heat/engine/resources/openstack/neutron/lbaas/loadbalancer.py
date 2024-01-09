#
#    Copyright 2015 IBM Corp.
#
#    All Rights Reserved.
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


class LoadBalancer(none_resource.NoneResource):
    """A resource for creating LBaaS v2 Load Balancers.

    This resource creates and manages Neutron LBaaS v2 Load Balancers,
    which allows traffic to be directed between servers.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='21.0.0',
        message=_('Use octavia instead.'),
        previous_status=support.SupportStatus(version='6.0.0')
    )


def resource_mapping():
    return {
        'OS::Neutron::LBaaS::LoadBalancer': LoadBalancer
    }
