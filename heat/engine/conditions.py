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

from heat.common import exception
from heat.engine import function


_in_progress = object()


class Conditions(object):
    def __init__(self, conditions_dict):
        assert isinstance(conditions_dict, collections.Mapping)
        self._conditions = conditions_dict
        self._resolved = {}

    def validate(self):
        for name, cond in six.iteritems(self._conditions):
            self._check_condition_type(name, cond)
            function.validate(cond)

    def _resolve(self, condition_name):
        resolved = function.resolve(self._conditions[condition_name])
        self._check_condition_type(condition_name, resolved)
        return resolved

    def _check_condition_type(self, condition_name, condition_defn):
        if not isinstance(condition_defn, (bool, function.Function)):
            msg_data = {'cd': condition_name, 'definition': condition_defn}
            message = _('The definition of condition "%(cd)s" is invalid: '
                        '%(definition)s') % msg_data
            raise exception.StackValidationFailed(
                error='Condition validation error',
                message=message)

    def is_enabled(self, condition_name):
        if condition_name is None:
            return True

        if isinstance(condition_name, bool):
            return condition_name

        if not (isinstance(condition_name, six.string_types) and
                condition_name in self._conditions):
            raise ValueError(_('Invalid condition "%s"') % condition_name)

        if condition_name not in self._resolved:
            self._resolved[condition_name] = _in_progress
            self._resolved[condition_name] = self._resolve(condition_name)

        result = self._resolved[condition_name]

        if result is _in_progress:
            message = _('Circular definition for condition '
                        '"%s"') % condition_name
            raise exception.StackValidationFailed(
                error='Condition validation error',
                message=message)

        return result

    def __repr__(self):
        return 'Conditions(%r)' % self._conditions
