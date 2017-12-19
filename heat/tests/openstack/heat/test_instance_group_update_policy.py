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

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.heat import instance_group as instgrp
from heat.engine import rsrc_defn
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


ig_tmpl_without_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {},
  "Resources" : {
    "JobServerGroup" : {
      "Type" : "OS::Heat::InstanceGroup",
      "Properties" : {
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "Size" : "10",
        "AvailabilityZones" : ["nova"]
      }
    },
    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"           : "foo",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''

ig_tmpl_with_bad_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {},
  "Resources" : {
    "JobServerGroup" : {
      "UpdatePolicy" : {
        "RollingUpdate": "foo"
      },
      "Type" : "OS::Heat::InstanceGroup",
      "Properties" : {
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "Size" : "10",
        "AvailabilityZones" : ["nova"]
      }
    },
    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"           : "foo",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''

ig_tmpl_with_default_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {},
  "Resources" : {
    "JobServerGroup" : {
      "UpdatePolicy" : {
        "RollingUpdate" : {
        }
      },
      "Type" : "OS::Heat::InstanceGroup",
      "Properties" : {
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "Size" : "10",
        "AvailabilityZones" : ["nova"]
      }
    },
    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"           : "foo",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''

ig_tmpl_with_updt_policy = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {},
  "Resources" : {
    "JobServerGroup" : {
      "UpdatePolicy" : {
        "RollingUpdate" : {
          "MinInstancesInService" : "1",
          "MaxBatchSize" : "2",
          "PauseTime" : "PT1S"
        }
      },
      "Type" : "OS::Heat::InstanceGroup",
      "Properties" : {
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "Size" : "10",
        "AvailabilityZones" : ["nova"]
      }
    },
    "JobServerConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"           : "foo",
        "InstanceType"      : "m1.medium",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''


class InstanceGroupTest(common.HeatTestCase):

    def setUp(self):
        super(InstanceGroupTest, self).setUp()
        self.fc = fakes_nova.FakeClient()
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()

    def get_launch_conf_name(self, stack, ig_name):
        return stack[ig_name].properties['LaunchConfigurationName']

    def test_parse_without_update_policy(self):
        tmpl = template_format.parse(ig_tmpl_without_updt_policy)
        stack = utils.parse_stack(tmpl)

        stack.validate()
        grp = stack['JobServerGroup']
        self.assertFalse(grp.update_policy['RollingUpdate'])

    def test_parse_with_update_policy(self):
        tmpl = template_format.parse(ig_tmpl_with_updt_policy)
        stack = utils.parse_stack(tmpl)

        stack.validate()
        grp = stack['JobServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertEqual(1, len(grp.update_policy))
        self.assertIn('RollingUpdate', grp.update_policy)
        policy = grp.update_policy['RollingUpdate']
        self.assertIsNotNone(policy)
        self.assertGreater(len(policy), 0)
        self.assertEqual(1, int(policy['MinInstancesInService']))
        self.assertEqual(2, int(policy['MaxBatchSize']))
        self.assertEqual('PT1S', policy['PauseTime'])

    def test_parse_with_default_update_policy(self):
        tmpl = template_format.parse(ig_tmpl_with_default_updt_policy)
        stack = utils.parse_stack(tmpl)

        stack.validate()
        grp = stack['JobServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertEqual(1, len(grp.update_policy))
        self.assertIn('RollingUpdate', grp.update_policy)
        policy = grp.update_policy['RollingUpdate']
        self.assertIsNotNone(policy)
        self.assertGreater(len(policy), 0)
        self.assertEqual(0, int(policy['MinInstancesInService']))
        self.assertEqual(1, int(policy['MaxBatchSize']))
        self.assertEqual('PT0S', policy['PauseTime'])

    def test_parse_with_bad_update_policy(self):
        tmpl = template_format.parse(ig_tmpl_with_bad_updt_policy)
        stack = utils.parse_stack(tmpl)
        self.assertRaises(exception.StackValidationFailed, stack.validate)

    def test_parse_with_bad_pausetime_in_update_policy(self):
        tmpl = template_format.parse(ig_tmpl_with_updt_policy)
        group = tmpl['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['RollingUpdate']

        # test against some random string
        policy['PauseTime'] = 'ABCD1234'
        stack = utils.parse_stack(tmpl)
        self.assertRaises(exception.StackValidationFailed, stack.validate)

        # test unsupported designator
        policy['PauseTime'] = 'P1YT1H'
        stack = utils.parse_stack(tmpl)
        self.assertRaises(exception.StackValidationFailed, stack.validate)

    def validate_update_policy_diff(self, current, updated):

        # load current stack
        current_tmpl = template_format.parse(current)
        current_stack = utils.parse_stack(current_tmpl)

        # get the json snippet for the current InstanceGroup resource
        current_grp = current_stack['JobServerGroup']
        current_snippets = dict((n, r.frozen_definition())
                                for n, r in current_stack.items())
        current_grp_json = current_snippets[current_grp.name]

        # load the updated stack
        updated_tmpl = template_format.parse(updated)
        updated_stack = utils.parse_stack(updated_tmpl)

        # get the updated json snippet for the InstanceGroup resource in the
        # context of the current stack
        updated_grp = updated_stack['JobServerGroup']
        updated_grp_json = updated_grp.t.freeze()

        # identify the template difference
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)
        self.assertTrue(tmpl_diff.update_policy_changed())

        # test application of the new update policy in handle_update
        current_grp._try_rolling_update = mock.MagicMock()
        current_grp.resize = mock.MagicMock()
        current_grp.handle_update(updated_grp_json, tmpl_diff, None)
        self.assertEqual(updated_grp_json._update_policy or {},
                         current_grp.update_policy.data)

    def test_update_policy_added(self):
        self.validate_update_policy_diff(ig_tmpl_without_updt_policy,
                                         ig_tmpl_with_updt_policy)

    def test_update_policy_updated(self):
        updt_template = json.loads(ig_tmpl_with_updt_policy)
        grp = updt_template['Resources']['JobServerGroup']
        policy = grp['UpdatePolicy']['RollingUpdate']
        policy['MinInstancesInService'] = '2'
        policy['MaxBatchSize'] = '4'
        policy['PauseTime'] = 'PT1M30S'
        self.validate_update_policy_diff(ig_tmpl_with_updt_policy,
                                         json.dumps(updt_template))

    def test_update_policy_removed(self):
        self.validate_update_policy_diff(ig_tmpl_with_updt_policy,
                                         ig_tmpl_without_updt_policy)


class InstanceGroupReplaceTest(common.HeatTestCase):
    def test_timeout_exception(self):
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        t = template_format.parse(ig_tmpl_with_updt_policy)
        stack = utils.parse_stack(t)

        defn = rsrc_defn.ResourceDefinition(
            'asg', 'OS::Heat::InstanceGroup',
            {'Size': 2,
             'AvailabilityZones': ['zoneb'],
             "LaunchConfigurationName": "LaunchConfig",
             "LoadBalancerNames": ["ElasticLoadBalancer"]})

        # the following test, effective_capacity is 12
        # batch_count = (effective_capacity + batch_size -1)//batch_size
        # = (12 + 2 - 1)//2 = 6
        # if (batch_count - 1)* pause_time > stack.time_out, to raise error
        # (6 - 1)*14*60 > 3600, so to raise error

        group = instgrp.InstanceGroup('asg', defn, stack)
        group._group_data().size = mock.Mock(return_value=12)
        self.assertRaises(ValueError,
                          group._replace, 10, 1, 14 * 60)
