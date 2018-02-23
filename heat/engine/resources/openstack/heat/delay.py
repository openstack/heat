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

import random

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

from oslo_utils import timeutils


class Delay(resource.Resource):
    """A resource that pauses for a configurable delay.

    By manipulating the dependency relationships between resources in the
    template, a delay can be inserted at an arbitrary point during e.g. stack
    creation or deletion. They delay will occur after any resource that it
    depends on during CREATE or SUSPEND, and before any resource that it
    depends on during DELETE or RESUME. Similarly, it will occur before any
    resource that depends on it during CREATE or SUSPEND, and after any
    resource thet depends on it during DELETE or RESUME.

    If a non-zero maximum jitter is specified, a random amount of jitter -
    chosen with uniform probability in the range from 0 to the product of the
    maximum jitter value and the jitter multiplier (1s by default) - is added
    to the minimum delay time. This can be used, for example, in the scaled
    unit of a large scaling group to prevent 'thundering herd' issues.
    """

    support_status = support.SupportStatus(version='11.0.0')

    _ALLOWED_ACTIONS = (
        resource.Resource.CREATE,
        resource.Resource.DELETE,
        resource.Resource.SUSPEND,
        resource.Resource.RESUME,
    )

    PROPERTIES = (
        MIN_WAIT_SECS, MAX_JITTER, JITTER_MULTIPLIER_SECS, ACTIONS,
    ) = (
        'min_wait', 'max_jitter', 'jitter_multiplier', 'actions',
    )

    properties_schema = {
        MIN_WAIT_SECS: properties.Schema(
            properties.Schema.NUMBER,
            _('Minimum time in seconds to wait during the specified actions.'),
            update_allowed=True,
            default=0,
            constraints=[
                constraints.Range(min=0)
            ]
        ),
        MAX_JITTER: properties.Schema(
            properties.Schema.NUMBER,
            _('Maximum jitter to add to the minimum wait time.'),
            update_allowed=True,
            default=0,
            constraints=[
                constraints.Range(min=0),
            ]
        ),
        JITTER_MULTIPLIER_SECS: properties.Schema(
            properties.Schema.NUMBER,
            _('Number of seconds to multiply the maximum jitter value by.'),
            update_allowed=True,
            default=1.0,
            constraints=[
                constraints.Range(min=0),
            ]
        ),
        ACTIONS: properties.Schema(
            properties.Schema.LIST,
            _('Actions during which the delay will occur.'),
            update_allowed=True,
            default=[resource.Resource.CREATE],
            constraints=[constraints.AllowedValues(_ALLOWED_ACTIONS)]
        ),
    }

    attributes_schema = {}

    def _delay_parameters(self):
        """Return a tuple of the min delay and max jitter, in seconds."""
        min_wait_secs = self.properties[self.MIN_WAIT_SECS]
        max_jitter_secs = (self.properties[self.MAX_JITTER] *
                           self.properties[self.JITTER_MULTIPLIER_SECS])
        return min_wait_secs, max_jitter_secs

    def validate(self):
        result = super(Delay, self).validate()
        if not self.stack.strict_validate:
            return result

        min_wait_secs, max_jitter_secs = self._delay_parameters()
        max_wait = min_wait_secs + max_jitter_secs
        if max_wait > self.stack.timeout_secs():
            raise exception.StackValidationFailed(_('%(res_type)s maximum '
                                                    'delay %(max_wait)ss '
                                                    'exceeds stack timeout.') %
                                                  {'res_type': self.type,
                                                   'max_wait': max_wait})
        return result

    def _wait_secs(self, action):
        """Return a (randomised) wait time for the specified action."""
        if action not in self.properties[self.ACTIONS]:
            return 0

        min_wait_secs, max_jitter_secs = self._delay_parameters()
        return min_wait_secs + (max_jitter_secs * random.random())

    def _handle_action(self):
        """Return a tuple of the start time in UTC and the time to wait."""
        return timeutils.utcnow(), self._wait_secs(self.action)

    @staticmethod
    def _check_complete(started_at, wait_secs):
        if not wait_secs:
            return True
        elapsed_secs = (timeutils.utcnow() - started_at).total_seconds()
        if elapsed_secs >= wait_secs:
            return True
        remaining = wait_secs - elapsed_secs
        if remaining >= 4:
            raise resource.PollDelay(int(remaining // 2))
        return False

    def handle_create(self):
        return self._handle_action()

    def handle_delete(self):
        return self._handle_action()

    def handle_suspend(self):
        return self._handle_action()

    def handle_resume(self):
        return self._handle_action()

    def check_create_complete(self, cookie):
        return self._check_complete(*cookie)

    def check_delete_complete(self, cookie):
        return self._check_complete(*cookie)

    def check_suspend_complete(self, cookie):
        return self._check_complete(*cookie)

    def check_resume_complete(self, cookie):
        return self._check_status_complete(*cookie)


def resource_mapping():
    return {
        'OS::Heat::Delay': Delay,
    }
