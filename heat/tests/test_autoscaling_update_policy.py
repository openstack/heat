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

import json

import mock
from oslo_config import cfg
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import function
from heat.engine import rsrc_defn
from heat.tests import common
from heat.tests import utils
from heat.tests.v1_1 import fakes as fakes_v1_1


asg_tmpl_without_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create autoscaling group.",
  "Parameters" : {},
  "Resources" : {
    "WebServerGroup" : {
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "10",
        "MaxSize" : "20",
        "LoadBalancerNames" : [ { "Ref" : "ElasticLoadBalancer" } ]
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
        "ImageId"           : "F20-x86_64-cfntools",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''

asg_tmpl_with_bad_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create autoscaling group.",
  "Parameters" : {},
  "Resources" : {
    "WebServerGroup" : {
      "UpdatePolicy": {
        "foo": {
        }
      },
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "10",
        "MaxSize" : "20"
      }
    },
    "LaunchConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"           : "F20-x86_64-cfntools",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''

asg_tmpl_with_default_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create autoscaling group.",
  "Parameters" : {},
  "Resources" : {
    "WebServerGroup" : {
      "UpdatePolicy" : {
        "AutoScalingRollingUpdate" : {
        }
      },
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "10",
        "MaxSize" : "20",
        "LoadBalancerNames" : [ { "Ref" : "ElasticLoadBalancer" } ]
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
        "ImageId"           : "F20-x86_64-cfntools",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''

asg_tmpl_with_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create autoscaling group.",
  "Parameters" : {},
  "Resources" : {
    "WebServerGroup" : {
      "UpdatePolicy" : {
        "AutoScalingRollingUpdate" : {
          "MinInstancesInService" : "1",
          "MaxBatchSize" : "2",
          "PauseTime" : "PT1S"
        }
      },
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "10",
        "MaxSize" : "20",
        "LoadBalancerNames" : [ { "Ref" : "ElasticLoadBalancer" } ]
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
        "ImageId"           : "F20-x86_64-cfntools",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''


class AutoScalingGroupTest(common.HeatTestCase):

    def setUp(self):
        super(AutoScalingGroupTest, self).setUp()
        self.fc = fakes_v1_1.FakeClient()
        self.stub_keystoneclient(username='test_stack.CfnLBUser')
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://127.0.0.1:8000/v1/waitcondition')

    def get_launch_conf_name(self, stack, ig_name):
        return stack[ig_name].properties['LaunchConfigurationName']

    def test_parse_without_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_without_updt_policy)
        stack = utils.parse_stack(tmpl)
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        stack.validate()
        grp = stack['WebServerGroup']
        self.assertFalse(grp.update_policy['AutoScalingRollingUpdate'])
        self.m.VerifyAll()

    def test_parse_with_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_updt_policy)
        stack = utils.parse_stack(tmpl)
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        stack.validate()
        tmpl_grp = tmpl['Resources']['WebServerGroup']
        tmpl_policy = tmpl_grp['UpdatePolicy']['AutoScalingRollingUpdate']
        tmpl_batch_sz = int(tmpl_policy['MaxBatchSize'])
        grp = stack['WebServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertEqual(1, len(grp.update_policy))
        self.assertIn('AutoScalingRollingUpdate', grp.update_policy)
        policy = grp.update_policy['AutoScalingRollingUpdate']
        self.assertTrue(policy and len(policy) > 0)
        self.assertEqual(1, int(policy['MinInstancesInService']))
        self.assertEqual(tmpl_batch_sz, int(policy['MaxBatchSize']))
        self.assertEqual('PT1S', policy['PauseTime'])
        self.m.VerifyAll()

    def test_parse_with_default_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_default_updt_policy)
        stack = utils.parse_stack(tmpl)
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()

        stack.validate()
        grp = stack['WebServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertEqual(1, len(grp.update_policy))
        self.assertIn('AutoScalingRollingUpdate', grp.update_policy)
        policy = grp.update_policy['AutoScalingRollingUpdate']
        self.assertTrue(policy and len(policy) > 0)
        self.assertEqual(0, int(policy['MinInstancesInService']))
        self.assertEqual(1, int(policy['MaxBatchSize']))
        self.assertEqual('PT0S', policy['PauseTime'])
        self.m.VerifyAll()

    def test_parse_with_bad_update_policy(self):
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()
        tmpl = template_format.parse(asg_tmpl_with_bad_updt_policy)
        stack = utils.parse_stack(tmpl)
        error = self.assertRaises(
            exception.StackValidationFailed, stack.validate)
        self.assertIn("foo", six.text_type(error))

    def test_parse_with_bad_pausetime_in_update_policy(self):
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()
        tmpl = template_format.parse(asg_tmpl_with_default_updt_policy)
        group = tmpl['Resources']['WebServerGroup']
        policy = group['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['PauseTime'] = 'P1YT1H'
        stack = utils.parse_stack(tmpl)
        error = self.assertRaises(
            exception.StackValidationFailed, stack.validate)
        self.assertIn("Only ISO 8601 duration format", six.text_type(error))

    def validate_update_policy_diff(self, current, updated):

        # load current stack
        current_tmpl = template_format.parse(current)
        current_stack = utils.parse_stack(current_tmpl)

        # get the json snippet for the current InstanceGroup resource
        current_grp = current_stack['WebServerGroup']
        current_snippets = dict((n, r.parsed_template())
                                for n, r in current_stack.items())
        current_grp_json = current_snippets[current_grp.name]

        # load the updated stack
        updated_tmpl = template_format.parse(updated)
        updated_stack = utils.parse_stack(updated_tmpl)

        # get the updated json snippet for the InstanceGroup resource in the
        # context of the current stack
        updated_grp = updated_stack['WebServerGroup']
        updated_grp_json = function.resolve(updated_grp.t)

        # identify the template difference
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)
        updated_policy = (updated_grp.t['UpdatePolicy']
                          if 'UpdatePolicy' in updated_grp.t else None)
        expected = {u'UpdatePolicy': updated_policy}
        self.assertEqual(expected, tmpl_diff)

        # test application of the new update policy in handle_update
        update_snippet = rsrc_defn.ResourceDefinition(
            current_grp.name,
            current_grp.type(),
            properties=updated_grp.t['Properties'],
            update_policy=updated_policy)
        current_grp._try_rolling_update = mock.MagicMock()
        current_grp.adjust = mock.MagicMock()
        current_grp.handle_update(update_snippet, tmpl_diff, None)
        if updated_policy is None:
            self.assertEqual({}, current_grp.update_policy.data)
        else:
            self.assertEqual(updated_policy, current_grp.update_policy.data)

    def test_update_policy_added(self):
        self.validate_update_policy_diff(asg_tmpl_without_updt_policy,
                                         asg_tmpl_with_updt_policy)

    def test_update_policy_updated(self):
        updt_template = json.loads(asg_tmpl_with_updt_policy)
        grp = updt_template['Resources']['WebServerGroup']
        policy = grp['UpdatePolicy']['AutoScalingRollingUpdate']
        policy['MinInstancesInService'] = '2'
        policy['MaxBatchSize'] = '4'
        policy['PauseTime'] = 'PT1M30S'
        self.validate_update_policy_diff(asg_tmpl_with_updt_policy,
                                         json.dumps(updt_template))

    def test_update_policy_removed(self):
        self.validate_update_policy_diff(asg_tmpl_with_updt_policy,
                                         asg_tmpl_without_updt_policy)
