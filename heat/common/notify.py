# Copyright 2014 Red Hat, Inc.
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

"""
Startup notification using a shell script or systemd NOTIFY_SOCKET
style notification
"""

from heat.openstack.common import importutils
from heat.openstack.common import log as logging
from heat.openstack.common import processutils

logger = logging.getLogger(__name__)


def startup_notify(notify_param):
    if not notify_param or notify_param == "":
        return
    try:
        notifier = importutils.import_module(notify_param)
    except ImportError:
        try:
            processutils.execute(notify_param, shell=True)
        except Exception as e:
            logger.error(_('Failed to execute onready command: %s') % str(e))
    else:
        notifier.notify()
