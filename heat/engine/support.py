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

from heat.common.i18n import _

SUPPORT_STATUSES = (UNKNOWN, SUPPORTED, DEPRECATED, UNSUPPORTED, HIDDEN
                    ) = ('UNKNOWN', 'SUPPORTED', 'DEPRECATED', 'UNSUPPORTED',
                         'HIDDEN')


class SupportStatus(object):

    def __init__(self, status=SUPPORTED, message=None,
                 version=None, previous_status=None, substitute_class=None):
        """Use SupportStatus for current status of object.

        :param status: current status of object.
        :param version: version of OpenStack, from which current status is
                    valid. It may be None, but need to be defined for correct
                    doc generating.
        :param message: specific status message for object.
        :param substitute_class: assign substitute class.
        """
        self.status = status
        self.substitute_class = substitute_class
        self.message = message
        self.version = version
        self.previous_status = previous_status

        self.validate()

    def validate(self):
        if (self.previous_status is not None and
                not isinstance(self.previous_status, SupportStatus)):
            raise ValueError(_('previous_status must be SupportStatus '
                               'instead of %s') % type(self.previous_status))

        if self.status not in SUPPORT_STATUSES:
            self.status = UNKNOWN
            self.message = _("Specified status is invalid, defaulting to"
                             " %s") % UNKNOWN

            self.version = None
            self.previous_status = None

    def to_dict(self):
            return {'status': self.status,
                    'message': self.message,
                    'version': self.version,
                    'previous_status': self.previous_status.to_dict()
                    if self.previous_status is not None else None}

    def is_substituted(self, substitute_class):
        if self.substitute_class is None:
            return False

        return substitute_class is self.substitute_class


def is_valid_status(status):
    return status in SUPPORT_STATUSES
