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

from heat.common import template_format
from heat.engine.resources import instance
from heat.engine import parser
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack


ig_template_before = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {},
  "Resources" : {
    "JobServerGroup" : {
      "Type" : "OS::Heat::InstanceGroup",
      "Properties" : {
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "Size" : "8",
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

ig_template_after = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {},
  "Resources" : {
    "JobServerGroup" : {
      "Type" : "OS::Heat::InstanceGroup",
      "Properties" : {
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "Size" : "8",
        "AvailabilityZones" : ["nova"]
      }
    },
    "JobServerConfig" : {
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

    def test_instance_group(self):

        # setup stack from the initial template
        tmpl = template_format.parse(ig_template_before)
        stack = parse_stack(tmpl)

        # test stack create
        # test the number of instance creation
        # test that physical resource name of launch configuration is used
        size = int(stack.resources['JobServerGroup'].properties['Size'])
        self._stub_create(size)
        self.m.ReplayAll()
        stack.create()
        self.m.VerifyAll()
        self.assertEqual(stack.status, stack.COMPLETE)
        conf = stack.resources['JobServerConfig']
        conf_name_pattern = '%s-JobServerConfig-[a-zA-Z0-9]+$' % stack.name
        regex_pattern = re.compile(conf_name_pattern)
        self.assertTrue(regex_pattern.match(conf.FnGetRefId()))

        # test stack update
        # test that launch configuration is replaced
        conf_name = self.get_launch_conf_name(stack, 'JobServerGroup')
        updated_tmpl = template_format.parse(ig_template_after)
        updated_stack = parse_stack(updated_tmpl)
        stack.update(updated_stack)
        updated_conf_name = self.get_launch_conf_name(stack, 'JobServerGroup')
        self.assertNotEqual(conf_name, updated_conf_name)
