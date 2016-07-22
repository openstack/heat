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

import collections

import six

from heat.common.i18n import _
from heat.engine import constraints


class ResourceTypeConstraint(constraints.BaseCustomConstraint):

    def validate(self, value, context, template=None):

        if not isinstance(value, collections.Sequence):
            return False

        if isinstance(value, six.string_types):
            value = [value]

        invalid_types = []
        for t in value:
            try:
                template.env.get_class(t)
            except Exception:
                invalid_types.append(t)

        if invalid_types:
            msg = _('The following resource types could not be found: %s')
            types = ','.join(invalid_types)
            self._error_message = msg % types
            return False

        return True
