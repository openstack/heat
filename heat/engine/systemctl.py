# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Start and Stop systemd services
"""
import dbus
import logging

logger = logging.getLogger('heat.engine.systemctl')

def systemctl(method, name, instance=None):

    bus = dbus.SystemBus()

    sysd = bus.get_object('org.freedesktop.systemd1',
                         '/org/freedesktop/systemd1')

    actual_method = ''
    if method == 'start':
        actual_method = 'StartUnit'
    elif method == 'stop':
        actual_method = 'StopUnit'
    else:
        raise

    m = sysd.get_dbus_method(actual_method, 'org.freedesktop.systemd1.Manager')

    if instance == None:
        service = '%s.service' % (name)
    else:
        service = '%s@%s.service' % (name, instance)

    try:
        result = m(service, 'replace')
    except dbus.DBusException as e:
        logger.error('couldn\'t %s %s error: %s' % (method, name, e))
        return None
    return result

