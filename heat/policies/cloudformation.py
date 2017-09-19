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

# These policies are for AWS CloudFormation-like APIs, so we won't list out
# the URI paths in rules.

POLICY_ROOT = 'cloudformation:%s'

cloudformation_policies = [
    policy.RuleDefault(
        name=POLICY_ROOT % 'ListStacks',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'CreateStack',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStacks',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DeleteStack',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'UpdateStack',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'CancelUpdateStack',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStackEvents',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'ValidateTemplate',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'GetTemplate',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'EstimateTemplateCost',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStackResource',
        check_str=base.RULE_ALLOW_EVERYBODY),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStackResources',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'ListStackResources',
        check_str=base.RULE_DENY_STACK_USER)
]


def list_rules():
    return cloudformation_policies
