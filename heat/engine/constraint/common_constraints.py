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

import croniter
import eventlet
import netaddr
import pytz
import six

from oslo_utils import netutils
from oslo_utils import timeutils

from heat.common.i18n import _
from heat.engine import constraints


class TestConstraintDelay(constraints.BaseCustomConstraint):

    def validate_with_client(self, client, value):
        eventlet.sleep(value)


class IPConstraint(constraints.BaseCustomConstraint):

    def validate(self, value, context):
        self._error_message = 'Invalid IP address'
        return netutils.is_valid_ip(value)


class MACConstraint(constraints.BaseCustomConstraint):

    def validate(self, value, context):
        self._error_message = 'Invalid MAC address.'
        return netaddr.valid_mac(value)


class CIDRConstraint(constraints.BaseCustomConstraint):

    def _validate_whitespace(self, data):
        self._error_message = ("Invalid net cidr '%s' contains "
                               "whitespace" % data)
        if len(data.split()) > 1:
            return False
        return True

    def validate(self, value, context):
        try:
            netaddr.IPNetwork(value)
            return self._validate_whitespace(value)
        except Exception as ex:
            self._error_message = 'Invalid net cidr %s ' % six.text_type(ex)
            return False


class ISO8601Constraint(object):

    def validate(self, value, context):
        try:
            timeutils.parse_isotime(value)
        except Exception:
            return False
        else:
            return True


class CRONExpressionConstraint(constraints.BaseCustomConstraint):

    def validate(self, value, context):
        if not value:
            return True
        try:
            croniter.croniter(value)
            return True
        except Exception as ex:
            self._error_message = _(
                'Invalid CRON expression: %s') % six.text_type(ex)
        return False


class TimezoneConstraint(constraints.BaseCustomConstraint):

    def validate(self, value, context):
        if not value:
            return True
        try:
            pytz.timezone(value)
            return True
        except Exception as ex:
            self._error_message = _(
                'Invalid timezone: %s') % six.text_type(ex)
        return False
