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

POLICY_ROOT = 'resource_types:%s'

resource_types_policies = [
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Nova::Flavor',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Cinder::EncryptedVolumeType',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Cinder::VolumeType',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Cinder::Quota',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Neutron::Quota',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Nova::Quota',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Manila::ShareType',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Neutron::ProviderNet',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Neutron::QoSPolicy',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Neutron::QoSBandwidthLimitRule',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Neutron::Segment',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Nova::HostAggregate',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Cinder::QoSSpecs',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Cinder::QoSAssociation',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Keystone::*',
        check_str=base.RULE_PROJECT_ADMIN),
    policy.RuleDefault(
        name=POLICY_ROOT % 'OS::Blazar::Host',
        check_str=base.RULE_PROJECT_ADMIN)
]


def list_rules():
    return resource_types_policies
