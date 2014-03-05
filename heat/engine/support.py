
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

SUPPORT_STATUSES = (UNKNOWN, SUPPORTED, PROTOTYPE, DEPRECATED,
                    UNSUPPORTED) = ('UNKNOWN', 'SUPPORTED', 'PROTOTYPE',
                                    'DEPRECATED', 'UNSUPPORTED')


class SupportStatus(object):

    def __init__(self, status=SUPPORTED, message=None, version=None):
        if status in SUPPORT_STATUSES:
            self.status = status
            self.message = message
            self.version = version
        else:
            self.status = UNKNOWN
            self.message = _("Specified status is invalid, defaulting to"
                             " %s") % UNKNOWN

            self.version = None

    def to_dict(self):
            return {'status': self.status,
                    'message': self.message,
                    'version': self.version}
