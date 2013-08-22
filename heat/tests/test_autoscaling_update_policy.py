# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import re

from heat.common import exception
from heat.common import template_format
from heat.engine.resources import instance
from heat.engine import parser
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests import utils


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
        "MinSize" : "1",
        "MaxSize" : "10"
      }
    },
    "LaunchConfig" : {
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
        "MinSize" : "1",
        "MaxSize" : "10"
      }
    },
    "LaunchConfig" : {
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
        "MinSize" : "1",
        "MaxSize" : "10"
      }
    },
    "LaunchConfig" : {
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

asg_tmpl_with_updt_policy_1 = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create autoscaling group.",
  "Parameters" : {},
  "Resources" : {
    "WebServerGroup" : {
      "UpdatePolicy" : {
        "AutoScalingRollingUpdate" : {
          "MinInstancesInService" : "1",
          "MaxBatchSize" : "3",
          "PauseTime" : "PT30S"
        }
      },
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "1",
        "MaxSize" : "10"
      }
    },
    "LaunchConfig" : {
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

asg_tmpl_with_updt_policy_2 = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create autoscaling group.",
  "Parameters" : {},
  "Resources" : {
    "WebServerGroup" : {
      "UpdatePolicy" : {
        "AutoScalingRollingUpdate" : {
          "MinInstancesInService" : "1",
          "MaxBatchSize" : "5",
          "PauseTime" : "PT30S"
        }
      },
      "Type" : "AWS::AutoScaling::AutoScalingGroup",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "LaunchConfigurationName" : { "Ref" : "LaunchConfig" },
        "MinSize" : "1",
        "MaxSize" : "10"
      }
    },
    "LaunchConfig" : {
      "Type" : "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"           : "foo",
        "InstanceType"      : "m1.large",
        "KeyName"           : "test",
        "SecurityGroups"    : [ "sg-1" ],
        "UserData"          : "jsconfig data"
      }
    }
  }
}
'''


class InstanceGroupTest(HeatTestCase):
    def setUp(self):
        super(InstanceGroupTest, self).setUp()
        setup_dummy_db()

    def _stub_create(self, num, instance_class=instance.Instance):
        """
        Expect creation of C{num} number of Instances.

        :param instance_class: The resource class to expect to be created
                               instead of instance.Instance.
        """

        self.m.StubOutWithMock(parser.Stack, 'validate')
        parser.Stack.validate()

        self.m.StubOutWithMock(instance_class, 'handle_create')
        self.m.StubOutWithMock(instance_class, 'check_create_complete')
        cookie = object()
        for x in range(num):
            instance_class.handle_create().AndReturn(cookie)
        instance_class.check_create_complete(cookie).AndReturn(False)
        instance_class.check_create_complete(
            cookie).MultipleTimes().AndReturn(True)

    def get_launch_conf_name(self, stack, ig_name):
        return stack.resources[ig_name].properties['LaunchConfigurationName']

    def test_parse_without_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_without_updt_policy)
        stack = utils.parse_stack(tmpl)
        grp = stack.resources['WebServerGroup']
        self.assertFalse(grp.update_policy['AutoScalingRollingUpdate'])

    def test_parse_with_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_updt_policy_1)
        stack = utils.parse_stack(tmpl)
        grp = stack.resources['WebServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertTrue(len(grp.update_policy) == 1)
        self.assertTrue('AutoScalingRollingUpdate' in grp.update_policy)
        policy = grp.update_policy['AutoScalingRollingUpdate']
        self.assertTrue(policy and len(policy) > 0)
        self.assertEqual(int(policy['MinInstancesInService']), 1)
        self.assertEqual(int(policy['MaxBatchSize']), 3)
        self.assertEqual(policy['PauseTime'], 'PT30S')

    def test_parse_with_default_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_default_updt_policy)
        stack = utils.parse_stack(tmpl)
        grp = stack.resources['WebServerGroup']
        self.assertTrue(grp.update_policy)
        self.assertTrue(len(grp.update_policy) == 1)
        self.assertTrue('AutoScalingRollingUpdate' in grp.update_policy)
        policy = grp.update_policy['AutoScalingRollingUpdate']
        self.assertTrue(policy and len(policy) > 0)
        self.assertEqual(int(policy['MinInstancesInService']), 0)
        self.assertEqual(int(policy['MaxBatchSize']), 1)
        self.assertEqual(policy['PauseTime'], 'PT0S')

    def test_parse_with_bad_update_policy(self):
        tmpl = template_format.parse(asg_tmpl_with_bad_updt_policy)
        stack = utils.parse_stack(tmpl)
        self.assertRaises(exception.StackValidationFailed, stack.validate)

    def validate_update_policy_diff(self, current, updated):

        # load current stack
        current_tmpl = template_format.parse(current)
        current_stack = utils.parse_stack(current_tmpl)

        # get the json snippet for the current InstanceGroup resource
        current_grp = current_stack.resources['WebServerGroup']
        current_snippets = dict((r.name, r.parsed_template())
                                for r in current_stack)
        current_grp_json = current_snippets[current_grp.name]

        # load the updated stack
        updated_tmpl = template_format.parse(updated)
        updated_stack = utils.parse_stack(updated_tmpl)

        # get the updated json snippet for the InstanceGroup resource in the
        # context of the current stack
        updated_grp = updated_stack.resources['WebServerGroup']
        updated_grp_json = current_stack.resolve_runtime_data(updated_grp.t)

        # identify the template difference
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)
        updated_policy = (updated_grp.t['UpdatePolicy']
                          if 'UpdatePolicy' in updated_grp.t else None)
        expected = {u'UpdatePolicy': updated_policy}
        self.assertEqual(tmpl_diff, expected)

    def test_update_policy_added(self):
        self.validate_update_policy_diff(asg_tmpl_without_updt_policy,
                                         asg_tmpl_with_updt_policy_1)

    def test_update_policy_updated(self):
        self.validate_update_policy_diff(asg_tmpl_with_updt_policy_1,
                                         asg_tmpl_with_updt_policy_2)

    def test_update_policy_removed(self):
        self.validate_update_policy_diff(asg_tmpl_with_updt_policy_1,
                                         asg_tmpl_without_updt_policy)

    def test_autoscaling_group_update(self):

        # setup stack from the initial template
        tmpl = template_format.parse(asg_tmpl_with_updt_policy_1)
        stack = utils.parse_stack(tmpl)
        nested = stack.resources['WebServerGroup'].nested()

        # test stack create
        # test the number of instance creation
        # test that physical resource name of launch configuration is used
        size = int(stack.resources['WebServerGroup'].properties['MinSize'])
        self._stub_create(size)
        self.m.ReplayAll()
        stack.create()
        self.m.VerifyAll()
        self.assertEqual(stack.state, ('CREATE', 'COMPLETE'))
        conf = stack.resources['LaunchConfig']
        conf_name_pattern = '%s-LaunchConfig-[a-zA-Z0-9]+$' % stack.name
        regex_pattern = re.compile(conf_name_pattern)
        self.assertTrue(regex_pattern.match(conf.FnGetRefId()))
        nested = stack.resources['WebServerGroup'].nested()
        self.assertTrue(len(nested.resources), size)

        # test stack update
        # test that update policy is updated
        # test that launch configuration is replaced
        current_grp = stack.resources['WebServerGroup']
        self.assertTrue('AutoScalingRollingUpdate'
                        in current_grp.update_policy)
        current_policy = current_grp.update_policy['AutoScalingRollingUpdate']
        self.assertTrue(current_policy and len(current_policy) > 0)
        self.assertEqual(int(current_policy['MaxBatchSize']), 3)
        conf_name = self.get_launch_conf_name(stack, 'WebServerGroup')
        updated_tmpl = template_format.parse(asg_tmpl_with_updt_policy_2)
        updated_stack = utils.parse_stack(updated_tmpl)
        stack.update(updated_stack)
        self.assertEqual(stack.state, ('UPDATE', 'COMPLETE'))
        updated_grp = stack.resources['WebServerGroup']
        self.assertTrue('AutoScalingRollingUpdate'
                        in updated_grp.update_policy)
        updated_policy = updated_grp.update_policy['AutoScalingRollingUpdate']
        self.assertTrue(updated_policy and len(updated_policy) > 0)
        self.assertEqual(int(updated_policy['MaxBatchSize']), 5)
        updated_conf_name = self.get_launch_conf_name(stack, 'WebServerGroup')
        self.assertNotEqual(conf_name, updated_conf_name)

    def test_autoscaling_group_update_policy_removed(self):

        # setup stack from the initial template
        tmpl = template_format.parse(asg_tmpl_with_updt_policy_1)
        stack = utils.parse_stack(tmpl)
        nested = stack.resources['WebServerGroup'].nested()

        # test stack create
        # test the number of instance creation
        # test that physical resource name of launch configuration is used
        size = int(stack.resources['WebServerGroup'].properties['MinSize'])
        self._stub_create(size)
        self.m.ReplayAll()
        stack.create()
        self.m.VerifyAll()
        self.assertEqual(stack.state, ('CREATE', 'COMPLETE'))
        conf = stack.resources['LaunchConfig']
        conf_name_pattern = '%s-LaunchConfig-[a-zA-Z0-9]+$' % stack.name
        regex_pattern = re.compile(conf_name_pattern)
        self.assertTrue(regex_pattern.match(conf.FnGetRefId()))
        nested = stack.resources['WebServerGroup'].nested()
        self.assertTrue(len(nested.resources), size)

        # test stack update
        # test that update policy is removed
        current_grp = stack.resources['WebServerGroup']
        self.assertTrue('AutoScalingRollingUpdate'
                        in current_grp.update_policy)
        current_policy = current_grp.update_policy['AutoScalingRollingUpdate']
        self.assertTrue(current_policy and len(current_policy) > 0)
        self.assertEqual(int(current_policy['MaxBatchSize']), 3)
        updated_tmpl = template_format.parse(asg_tmpl_without_updt_policy)
        updated_stack = utils.parse_stack(updated_tmpl)
        stack.update(updated_stack)
        self.assertEqual(stack.state, ('UPDATE', 'COMPLETE'))
        updated_grp = stack.resources['WebServerGroup']
        self.assertFalse(updated_grp.update_policy['AutoScalingRollingUpdate'])
