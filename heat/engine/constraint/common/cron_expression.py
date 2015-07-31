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
import six

from heat.common.i18n import _
from heat.engine import constraints


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
