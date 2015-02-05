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

as_params = {'KeyName': 'test', 'ImageId': 'foo'}
as_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "AutoScaling Test",
  "Parameters" : {
  "ImageId": {"Type": "String"},
  "KeyName": {"Type": "String"}
  },
  "Resources" : {
    "WebServerGroup" : {
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "1",
        "MaxSize" : "5",
        "LoadBalancerNames" : [ { "Ref" : "ElasticLoadBalancer" } ]
      }
    },
    "WebServerScaleUpPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : { "Ref" : "WebServerGroup" },
        "Cooldown" : "60",
        "ScalingAdjustment" : "1"
      }
    },
    "WebServerScaleDownPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : { "Ref" : "WebServerGroup" },
        "Cooldown" : "60",
        "ScalingAdjustment" : "-1"
      }
    },
    "ElasticLoadBalancer" : {
        "Type" : "AWS::ElasticLoadBalancing::LoadBalancer",
        "Properties" : {
            "AvailabilityZones" : ["nova"],
            "Listeners" : [ {
                "LoadBalancerPort" : "80",
                "InstancePort" : "80",
                "Protocol" : "HTTP"
            }]
        }
    },
    "LaunchConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId" : {"Ref": "ImageId"},
        "InstanceType"   : "bar",
        "BlockDeviceMappings": [
            {
                "DeviceName": "vdb",
                "Ebs": {"SnapshotId": "9ef5496e-7426-446a-bbc8-01f84d9c9972",
                        "DeleteOnTermination": "True"}
            }]
      }
    }
  }
}
'''

as_heat_template = '''
    heat_template_version: 2013-05-23
    description: AutoScaling Test
    resources:
      my-group:
        type: OS::Heat::AutoScalingGroup
        properties:
          max_size: 5
          min_size: 1
          resource:
            type: ResourceWithPropsAndAttrs
            properties:
                Foo: hello
      my-policy:
        type: OS::Heat::ScalingPolicy
        properties:
          auto_scaling_group_id: {get_resource: my-group}
          scaling_adjustment: 1
          adjustment_type: change_in_capacity
          cooldown: 60
'''

as_template_bad_group = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Parameters" : {
  "ImageId": {"Type": "String"},
  "KeyName": {"Type": "String"}
  },
  "Resources" : {
    "WebServerScaleUpPolicy" : {
      "Type" : "AWS::AutoScaling::ScalingPolicy",
      "Properties" : {
        "AdjustmentType" : "ChangeInCapacity",
        "AutoScalingGroupName" : "not a real group",
        "Cooldown" : "60",
        "ScalingAdjustment" : "1"
      }
    }
  }
}
'''

as_heat_template_bad_group = '''
    heat_template_version: 2013-05-23
    description: AutoScaling Test
    resources:
      my-policy:
        type: OS::Heat::ScalingPolicy
        properties:
          auto_scaling_group_id: bad-group
          scaling_adjustment: 1
          adjustment_type: change_in_capacity
          cooldown: 60
'''
