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
from heat.engine.resources.openstack.heat import none_resource
from heat.engine import support


class CloudWatchAlarm(none_resource.NoneResource):
    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=_('OS::Heat::CWLiteAlarm resource has been removed '
                  'since version 10.0.0. Existing stacks can still '
                  'use it, where it would do nothing for update/delete.'),
        version='5.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            version='2014.2')
    )


def resource_mapping():
    cfg.CONF.import_opt('enable_cloud_watch_lite', 'heat.common.config')
    if cfg.CONF.enable_cloud_watch_lite:
        return {
            'OS::Heat::CWLiteAlarm': CloudWatchAlarm,
        }
    else:
        return {}
