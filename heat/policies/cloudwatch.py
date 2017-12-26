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


# These policies are for AWS CloudWatch-like APIs, so we won't list out the URI
# paths in rules.


POLICY_ROOT = 'cloudwatch:%s'


cloudwatch_policies = [
    policy.RuleDefault(
        name=POLICY_ROOT % 'DeleteAlarms',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeAlarmHistory',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeAlarms',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DescribeAlarmsForMetric',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'DisableAlarmActions',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'EnableAlarmActions',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'GetMetricStatistics',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'ListMetrics',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'PutMetricAlarm',
        check_str=base.RULE_DENY_STACK_USER),
    policy.RuleDefault(
        name=POLICY_ROOT % 'PutMetricData',
        check_str=base.RULE_ALLOW_EVERYBODY),
    policy.RuleDefault(
        name=POLICY_ROOT % 'SetAlarmState',
        check_str=base.RULE_DENY_STACK_USER)
]


def list_rules():
    return cloudwatch_policies
