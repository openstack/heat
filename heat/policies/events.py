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

from oslo_log import versionutils
from oslo_policy import policy

from heat.policies import base

POLICY_ROOT = 'events:%s'

DEPRECATED_REASON = """
The events API now supports system scope and default roles.
"""

deprecated_index = policy.DeprecatedRule(
    name=POLICY_ROOT % 'index',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_show = policy.DeprecatedRule(
    name=POLICY_ROOT % 'show',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)


events_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'index',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='List events.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'events',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_index
    ),
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'show',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        description='Show event.',
        operations=[
            {
                'path': '/v1/{tenant_id}/stacks/{stack_name}/{stack_id}/'
                'resources/{resource_name}/events/{event_id}',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_show
    )
]


def list_rules():
    return events_policies
