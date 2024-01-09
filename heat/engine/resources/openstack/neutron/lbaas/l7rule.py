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


class L7Rule(none_resource.NoneResource):
    """A resource for managing LBaaS v2 L7Rules.

    This resource manages Neutron-LBaaS v2 L7Rules, which represent
    a set of attributes that defines which part of the request should
    be matched and how it should be matched.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='21.0.0',
        message=_('Use octavia instead.'),
        previous_status=support.SupportStatus(version='7.0.0')
    )


def resource_mapping():
    return {
        'OS::Neutron::LBaaS::L7Rule': L7Rule
    }
