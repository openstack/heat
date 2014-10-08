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
from oslo import messaging
import osprofiler.profiler
import osprofiler.web

from heat.common import context
from heat.common import messaging as rpc_messaging
from heat.openstack.common import log as logging

cfg.CONF.import_opt('profiler_enabled', 'heat.common.config', group='profiler')

LOG = logging.getLogger(__name__)


def setup(binary, host):
    if cfg.CONF.profiler.profiler_enabled:
        _notifier = osprofiler.notifier.create(
            "Messaging", messaging, context.get_admin_context().to_dict(),
            rpc_messaging.TRANSPORT, "heat", binary, host)
        osprofiler.notifier.set(_notifier)
        LOG.warning("OSProfiler is enabled.\nIt means that person who knows "
                    "any of hmac_keys that are specified in "
                    "/etc/heat/api-paste.ini can trace his requests. \n"
                    "In real life only operator can read this file so there "
                    "is no security issue. Note that even if person can "
                    "trigger profiler, only admin user can retrieve trace "
                    "information.\n"
                    "To disable OSprofiler set in heat.conf:\n"
                    "[profiler]\nenabled=false")
    else:
        osprofiler.web.disable()
