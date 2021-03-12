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

# These policies are for AWS CloudFormation-like APIs, so we won't list out
# the URI paths in rules.

DEPRECATED_REASON = """
The cloud formation API now supports system scope and default roles.
"""

POLICY_ROOT = 'cloudformation:%s'

deprecated_list_stacks = policy.DeprecatedRule(
    name=POLICY_ROOT % 'ListStacks',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_create_stack = policy.DeprecatedRule(
    name=POLICY_ROOT % 'CreateStack',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_describe_stacks = policy.DeprecatedRule(
    name=POLICY_ROOT % 'DescribeStacks',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_delete_stack = policy.DeprecatedRule(
    name=POLICY_ROOT % 'DeleteStack',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_update_stack = policy.DeprecatedRule(
    name=POLICY_ROOT % 'UpdateStack',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_cancel_update_stack = policy.DeprecatedRule(
    name=POLICY_ROOT % 'CancelUpdateStack',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_describe_stack_events = policy.DeprecatedRule(
    name=POLICY_ROOT % 'DescribeStackEvents',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_validate_template = policy.DeprecatedRule(
    name=POLICY_ROOT % 'ValidateTemplate',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_get_template = policy.DeprecatedRule(
    name=POLICY_ROOT % 'GetTemplate',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_estimate_template_cost = policy.DeprecatedRule(
    name=POLICY_ROOT % 'EstimateTemplateCost',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_describe_stack_resource = policy.DeprecatedRule(
    name=POLICY_ROOT % 'DescribeStackResource',
    check_str=base.RULE_ALLOW_EVERYBODY,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_describe_stack_resources = policy.DeprecatedRule(
    name=POLICY_ROOT % 'DescribeStackResources',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)
deprecated_list_stack_resources = policy.DeprecatedRule(
    name=POLICY_ROOT % 'ListStackResources',
    check_str=base.RULE_DENY_STACK_USER,
    deprecated_reason=DEPRECATED_REASON,
    deprecated_since=versionutils.deprecated.WALLABY
)

cloudformation_policies = [
    policy.RuleDefault(
        name=POLICY_ROOT % 'ListStacks',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_list_stacks
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'CreateStack',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_create_stack
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStacks',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_describe_stacks
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DeleteStack',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_delete_stack
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'UpdateStack',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_update_stack
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'CancelUpdateStack',
        check_str=base.SYSTEM_ADMIN_OR_PROJECT_MEMBER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_cancel_update_stack
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStackEvents',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_describe_stack_events
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'ValidateTemplate',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_validate_template
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'GetTemplate',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_get_template
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'EstimateTemplateCost',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_estimate_template_cost
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStackResource',
        check_str=base.SYSTEM_OR_PROJECT_READER_OR_STACK_USER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_describe_stack_resource
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeStackResources',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_describe_stack_resources
    ),
    policy.RuleDefault(
        name=POLICY_ROOT % 'ListStackResources',
        check_str=base.SYSTEM_OR_PROJECT_READER,
        scope_types=['system', 'project'],
        deprecated_rule=deprecated_list_stack_resources
    )
]


def list_rules():
    return cloudformation_policies
