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

from heat.common.i18n import _
from heat.engine.resources.openstack.heat import none_resource
from heat.engine import support

LOG = logging.getLogger(__name__)


class Restarter(none_resource.NoneResource):

    support_status = support.SupportStatus(
        status=support.HIDDEN,
        version='10.0.0',
        message=_('The HARestarter resource type has been removed. Existing '
                  'stacks containing HARestarter resources can still be '
                  'used, but the HARestarter resource will be a placeholder '
                  'that does nothing.'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=_('The HARestarter resource type is deprecated and will '
                      'be removed in a future release of Heat, once it has '
                      'support for auto-healing any type of resource. Note '
                      'that HARestarter does *not* actually restart '
                      'servers - it deletes and then recreates them. It also '
                      'does the same to all dependent resources, and may '
                      'therefore exhibit unexpected and undesirable '
                      'behaviour. Instead, use the mark-unhealthy API to '
                      'mark a resource as needing replacement, and then a '
                      'stack update to perform the replacement while '
                      'respecting  the dependencies and not deleting them '
                      'unnecessarily.'),
            version='2015.1'))


def resource_mapping():
    return {
        'OS::Heat::HARestarter': Restarter,
    }
