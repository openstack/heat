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

from oslo.config import cfg

from heat.openstack.common import log
from heat.openstack.common.notifier import api as notifier_api
from heat.engine import api as engine_api

LOG = log.getLogger(__name__)
SERVICE = 'orchestration'
CONF = cfg.CONF
CONF.import_opt('default_notification_level',
                'heat.openstack.common.notifier.api')
CONF.import_opt('default_publisher_id',
                'heat.openstack.common.notifier.api')


def send(stack):
    """Send usage notifications to the configured notification driver."""

    publisher_id = CONF.default_publisher_id
    if publisher_id is None:
        publisher_id = notifier_api.publisher_id(SERVICE)

    # The current notifications have a start/end:
    # see: https://wiki.openstack.org/wiki/SystemUsageData
    # so to be consistant we translate our status into a known start/end/error
    # suffix.
    level = CONF.default_notification_level.upper()
    if stack.status == stack.IN_PROGRESS:
        suffix = 'start'
    elif stack.status == stack.COMPLETE:
        suffix = 'end'
    else:
        suffix = 'error'
        level = notifier_api.ERROR

    event_type = '%s.%s.%s' % (SERVICE, stack.action.lower(), suffix)

    notifier_api.notify(stack.context, publisher_id,
                        event_type, level,
                        engine_api.format_notification_body(stack))
