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

from heat.engine import api as engine_api
from heat.engine import notification


def send(stack,
         adjustment=None,
         adjustment_type=None,
         capacity=None,
         groupname=None,
         message='error',
         suffix=None):
    """Send autoscaling notifications to the configured notification driver."""

    # see: https://wiki.openstack.org/wiki/SystemUsageData

    event_type = '%s.%s' % ('autoscaling', suffix)
    body = engine_api.format_notification_body(stack)
    body['adjustment_type'] = adjustment_type
    body['adjustment'] = adjustment
    body['capacity'] = capacity
    body['groupname'] = groupname
    body['message'] = message

    level = notification.get_default_level()
    if suffix == 'error':
        level = notification.ERROR

    notification.notify(stack.context, event_type, level, body)
