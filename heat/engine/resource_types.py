# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Register of resource types and their mapping to Resource classes.
"""


from heat.engine import resources

from heat.engine import cloud_watch
from heat.engine import eip
from heat.engine import escalation_policy
from heat.engine import instance
from heat.engine import security_group
from heat.engine import user
from heat.engine import volume
from heat.engine import wait_condition


_resource_classes = {
    'AWS::CloudFormation::WaitCondition': wait_condition.WaitCondition,
    'AWS::CloudFormation::WaitConditionHandle':
        wait_condition.WaitConditionHandle,
    'AWS::CloudWatch::Alarm': cloud_watch.CloudWatchAlarm,
    'AWS::EC2::EIP': eip.ElasticIp,
    'AWS::EC2::EIPAssociation': eip.ElasticIpAssociation,
    'AWS::EC2::Instance': instance.Instance,
    'AWS::EC2::SecurityGroup': security_group.SecurityGroup,
    'AWS::EC2::Volume': volume.Volume,
    'AWS::EC2::VolumeAttachment': volume.VolumeAttachment,
    'AWS::IAM::User': user.User,
    'AWS::IAM::AccessKey': user.AccessKey,
    'HEAT::HA::Restarter': instance.Restarter,
    'HEAT::Recovery::EscalationPolicy': escalation_policy.EscalationPolicy,
}


def getClass(resource_type):
    """Return the appropriate Resource class for the resource type."""
    return _resource_classes.get(resource_type, resources.GenericResource)
