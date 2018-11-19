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

from oslo_config import cfg

from heat.common.i18n import _
from heat.common import messaging

SERVICE = 'orchestration'
INFO = 'INFO'
ERROR = 'ERROR'

notifier_opts = [
    cfg.StrOpt('default_notification_level',
               default=INFO,
               help=_('Default notification level for outgoing '
                      'notifications.')),
    cfg.StrOpt('default_publisher_id',
               help=_('Default publisher_id for outgoing notifications.')),
]
CONF = cfg.CONF
CONF.register_opts(notifier_opts)


def _get_default_publisher():
    publisher_id = CONF.default_publisher_id
    if publisher_id is None:
        publisher_id = "%s.%s" % (SERVICE, CONF.host)
    return publisher_id


def get_default_level():
    return CONF.default_notification_level.upper()


def notify(context, event_type, level, body):
    client = messaging.get_notifier(_get_default_publisher())

    method = getattr(client, level.lower())
    method(context, "%s.%s" % (SERVICE, event_type), body)


def list_opts():
    yield None, notifier_opts
