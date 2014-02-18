# Copyright 2012 Red Hat, Inc.
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
Helper module for systemd start-up completion notification.
Used for "onready" configuration parameter in heat.conf
"""

import os
import socket

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


def _sd_notify(msg):
    sysd = os.getenv('NOTIFY_SOCKET')
    if sysd:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if sysd.startswith('@'):
            # abstract namespace socket
            sysd = '\0%s' % sysd[1:]
        sock.connect(sysd)
        sock.sendall(msg)
        sock.close()
    else:
        logger.warning(_('Unable to notify systemd of startup completion:'
                         ' NOTIFY_SOCKET not set'))


def notify():
    _sd_notify('READY=1')
