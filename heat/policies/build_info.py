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

from oslo_policy import policy

from heat.policies import base

POLICY_ROOT = 'build_info:%s'

build_info_policies = [
    policy.DocumentedRuleDefault(
        name=POLICY_ROOT % 'build_info',
        check_str=base.RULE_DENY_STACK_USER,
        description='Show build information.',
        operations=[
            {
                'path': '/v1/{tenant_id}/build_info',
                'method': 'GET'
            }
        ]
    )
]


def list_rules():
    return build_info_policies
