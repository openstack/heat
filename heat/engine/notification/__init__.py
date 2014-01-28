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

LOG = log.getLogger(__name__)
SERVICE = 'orchestration'
CONF = cfg.CONF
CONF.import_opt('default_notification_level',
                'heat.openstack.common.notifier.api')
CONF.import_opt('default_publisher_id',
                'heat.openstack.common.notifier.api')


def _get_default_publisher():
    publisher_id = CONF.default_publisher_id
    if publisher_id is None:
        publisher_id = notifier_api.publisher_id(SERVICE)
    return publisher_id


def get_default_level():
    return CONF.default_notification_level.upper()


def notify(context, event_type, level, body):

    notifier_api.notify(context, _get_default_publisher(),
                        "%s.%s" % (SERVICE, event_type),
                        level, body)
