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

DEPRECATED_REASON = """
The build API now supports system scope and default roles.
"""

POLICY_ROOT = 'build_info:%s'

deprecated_build_info = policy.DeprecatedRule(
    name=POLICY_ROOT % 'build_info',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)


build_info_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'build_info',
        check_str=base.PROJECT_READER,
        scope_types=['project'],
        description='Show build information.',
        operations=[
            {
                'path': '/v1/{tenant_id}/build_info',
                'method': 'GET'
            }
        ],
        deprecated_rule=deprecated_build_info
    )
]


def list_rules():
    return build_info_policies
