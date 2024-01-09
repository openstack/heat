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


class L7Policy(none_resource.NoneResource):
    """A resource for managing LBaaS v2 L7Policies.

    This resource manages Neutron-LBaaS v2 L7Policies, which represent
    a collection of L7Rules. L7Policy holds the action that should be performed
    when the rules are matched (Redirect to Pool, Redirect to URL, Reject).
    L7Policy holds a Listener id, so a Listener can evaluate a collection of
    L7Policies. L7Policy will return True when all of the L7Rules that belong
    to this L7Policy are matched. L7Policies under a specific Listener are
    ordered and the first l7Policy that returns a match will be executed.
    When none of the policies match the request gets forwarded to
    listener.default_pool_id.
    """

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='21.0.0',
        message=_('Use octavia instead.'),
        previous_status=support.SupportStatus(version='7.0.0')
    )


def resource_mapping():
    return {
        'OS::Neutron::LBaaS::L7Policy': L7Policy
    }
