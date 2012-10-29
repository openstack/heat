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

from heat.engine.resources import autoscaling
from heat.engine.resources import cloud_watch
from heat.engine.resources import dbinstance
from heat.engine.resources import eip
from heat.engine.resources import instance
from heat.engine.resources import loadbalancer
from heat.engine.resources import s3
from heat.engine.resources import security_group
from heat.engine.resources import stack
from heat.engine.resources import user
from heat.engine.resources import volume
from heat.engine.resources import wait_condition
from heat.engine.resources.quantum import floatingip
from heat.engine.resources.quantum import net
from heat.engine.resources.quantum import port
from heat.engine.resources.quantum import router
from heat.engine.resources.quantum import subnet


_resource_classes = {
    'AWS::CloudFormation::Stack': stack.Stack,
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
    'AWS::ElasticLoadBalancing::LoadBalancer': loadbalancer.LoadBalancer,
    'AWS::S3::Bucket': s3.S3Bucket,
    'AWS::IAM::User': user.User,
    'AWS::IAM::AccessKey': user.AccessKey,
    'HEAT::HA::Restarter': instance.Restarter,
    'AWS::AutoScaling::LaunchConfiguration': autoscaling.LaunchConfiguration,
    'AWS::AutoScaling::AutoScalingGroup': autoscaling.AutoScalingGroup,
    'AWS::AutoScaling::ScalingPolicy': autoscaling.ScalingPolicy,
    'AWS::RDS::DBInstance': dbinstance.DBInstance,
    'OS::Quantum::FloatingIP': floatingip.FloatingIP,
    'OS::Quantum::FloatingIPAssociation': floatingip.FloatingIPAssociation,
    'OS::Quantum::Net': net.Net,
    'OS::Quantum::Port': port.Port,
    'OS::Quantum::Router': router.Router,
    'OS::Quantum::RouterInterface': router.RouterInterface,
    'OS::Quantum::RouterGateway': router.RouterGateway,
    'OS::Quantum::Subnet': subnet.Subnet,
}


def get_class(resource_type):
    return _resource_classes.get(resource_type)
