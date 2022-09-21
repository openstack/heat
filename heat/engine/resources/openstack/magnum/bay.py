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


class Bay(none_resource.NoneResource):
    """A resource that creates a Magnum Bay.

    This resource has been deprecated in favor of OS::Magnum::Cluster.
    """

    deprecation_msg = _('Please use OS::Magnum::Cluster instead.')
    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=deprecation_msg,
        version='11.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=deprecation_msg,
            version='9.0.0',
            previous_status=support.SupportStatus(
                status=support.SUPPORTED,
                version='6.0.0')
        )
    )


def resource_mapping():
    return {
        'OS::Magnum::Bay': Bay
    }
