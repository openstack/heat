
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

import copy
import json

import mox
from testtools.matchers import MatchesRegex

from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine.resources import image
from heat.engine.resources import instance
from heat.engine.resources import nova_keypair
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


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


class InstanceGroupTest(HeatTestCase):

    def setUp(self):
        super(InstanceGroupTest, self).setUp()
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()

    def _stub_validate(self):
        self.m.StubOutWithMock(parser.Stack, 'validate')
        parser.Stack.validate().MultipleTimes()
        self.m.StubOutWithMock(nova_keypair.KeypairConstraint, 'validate')
        nova_keypair.KeypairConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(image.ImageConstraint, 'validate')
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

    def _stub_grp_create(self, capacity):
        """
        Expect creation of instances to capacity
        """
        self._stub_validate()

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')

        cookie = object()
        for x in range(capacity):
            instance.Instance.handle_create().AndReturn(cookie)
            instance.Instance.check_create_complete(cookie).AndReturn(True)

    def _stub_grp_replace(self,
                          num_creates_expected_on_updt=0,
                          num_deletes_expected_on_updt=0):
        """
        Expect update replacement of the instances
        """
        self._stub_validate()

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        self.m.StubOutWithMock(instance.Instance, 'destroy')

        cookie = object()
        for i in range(num_creates_expected_on_updt):
            instance.Instance.handle_create().AndReturn(cookie)
            instance.Instance.check_create_complete(cookie).AndReturn(True)
        for i in range(num_deletes_expected_on_updt):
            instance.Instance.destroy().AndReturn(None)

    def _stub_grp_update(self,
                         num_creates_expected_on_updt=0,
                         num_deletes_expected_on_updt=0):
        """
        Expect update of the instances
        """
        self.m.StubOutWithMock(instance.Instance, 'nova')
        instance.Instance.nova().MultipleTimes().AndReturn(self.fc)

        def activate_status(server):
            server.status = 'VERIFY_RESIZE'

        return_server = self.fc.servers.list()[1]
        return_server.id = 1234
        return_server.get = activate_status.__get__(return_server)

        self.m.StubOutWithMock(self.fc.servers, 'get')
        self.m.StubOutWithMock(self.fc.client, 'post_servers_1234_action')

        self.fc.servers.get(mox.IgnoreArg()).\
            MultipleTimes().AndReturn(return_server)
        self.fc.client.post_servers_1234_action(
            body={'resize': {'flavorRef': 3}}).\
            MultipleTimes().AndReturn((202, None))
        self.fc.client.post_servers_1234_action(
            body={'confirmResize': None}).\
            MultipleTimes().AndReturn((202, None))

        self._stub_grp_replace(num_creates_expected_on_updt,
                               num_deletes_expected_on_updt)

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
        self.assertTrue(policy and len(policy) > 0)
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
        self.assertTrue(policy and len(policy) > 0)
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
        current_snippets = dict((n, r.parsed_template())
                                for n, r in current_stack.items())
        current_grp_json = current_snippets[current_grp.name]

        # load the updated stack
        updated_tmpl = template_format.parse(updated)
        updated_stack = utils.parse_stack(updated_tmpl)

        # get the updated json snippet for the InstanceGroup resource in the
        # context of the current stack
        updated_grp = updated_stack['JobServerGroup']
        updated_grp_json = current_stack.resolve_runtime_data(updated_grp.t)

        # identify the template difference
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)
        updated_policy = (updated_grp.t['UpdatePolicy']
                          if 'UpdatePolicy' in updated_grp.t else None)
        expected = {u'UpdatePolicy': updated_policy}
        self.assertEqual(expected, tmpl_diff)

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

    def update_instance_group(self, init_template, updt_template,
                              num_updates_expected_on_updt,
                              num_creates_expected_on_updt,
                              num_deletes_expected_on_updt,
                              update_replace):

        # setup stack from the initial template
        tmpl = template_format.parse(init_template)
        stack = utils.parse_stack(tmpl)
        stack.validate()

        # test stack create
        size = int(stack['JobServerGroup'].properties['Size'])
        self._stub_grp_create(size)
        self.m.ReplayAll()
        stack.create()
        self.m.VerifyAll()
        self.assertEqual(('CREATE', 'COMPLETE'), stack.state)

        # test that update policy is loaded
        current_grp = stack['JobServerGroup']
        self.assertIn('RollingUpdate', current_grp.update_policy)
        current_policy = current_grp.update_policy['RollingUpdate']
        self.assertTrue(current_policy)
        self.assertTrue(len(current_policy) > 0)
        init_grp_tmpl = tmpl['Resources']['JobServerGroup']
        init_roll_updt = init_grp_tmpl['UpdatePolicy']['RollingUpdate']
        init_batch_sz = int(init_roll_updt['MaxBatchSize'])
        self.assertEqual(init_batch_sz, int(current_policy['MaxBatchSize']))

        # test that physical resource name of launch configuration is used
        conf = stack['JobServerConfig']
        conf_name_pattern = '%s-JobServerConfig-[a-zA-Z0-9]+$' % stack.name
        self.assertThat(conf.FnGetRefId(), MatchesRegex(conf_name_pattern))

        # get launch conf name here to compare result after update
        conf_name = self.get_launch_conf_name(stack, 'JobServerGroup')

        # test the number of instances created
        nested = stack['JobServerGroup'].nested()
        self.assertEqual(size, len(nested.resources))

        # clean up for next test
        self.m.UnsetStubs()

        # saves info from initial list of instances for comparison later
        init_instances = current_grp.get_instances()
        init_names = current_grp.get_instance_names()
        init_images = [(i.name, i.t['Properties']['ImageId'])
                       for i in init_instances]
        init_flavors = [(i.name, i.t['Properties']['InstanceType'])
                        for i in init_instances]

        # test stack update
        updated_tmpl = template_format.parse(updt_template)
        updated_stack = utils.parse_stack(updated_tmpl)
        new_grp_tmpl = updated_tmpl['Resources']['JobServerGroup']
        new_roll_updt = new_grp_tmpl['UpdatePolicy']['RollingUpdate']
        new_batch_sz = int(new_roll_updt['MaxBatchSize'])
        self.assertNotEqual(new_batch_sz, init_batch_sz)
        if update_replace:
            self._stub_grp_replace(size, size)
        else:
            self._stub_grp_update(num_creates_expected_on_updt,
                                  num_deletes_expected_on_updt)
        self.stub_wallclock()
        self.m.ReplayAll()
        stack.update(updated_stack)
        self.m.VerifyAll()
        self.assertEqual(('UPDATE', 'COMPLETE'), stack.state)

        # test that the update policy is updated
        updated_grp = stack['JobServerGroup']
        self.assertIn('RollingUpdate', updated_grp.update_policy)
        updated_policy = updated_grp.update_policy['RollingUpdate']
        self.assertTrue(updated_policy)
        self.assertTrue(len(updated_policy) > 0)
        self.assertEqual(new_batch_sz, int(updated_policy['MaxBatchSize']))

        # test that the launch configuration is replaced
        updated_conf_name = self.get_launch_conf_name(stack, 'JobServerGroup')
        self.assertNotEqual(conf_name, updated_conf_name)

        # test that the group size are the same
        updt_instances = updated_grp.get_instances()
        updt_names = updated_grp.get_instance_names()
        self.assertEqual(len(init_names), len(updt_names))

        # test that the appropriate number of instance names are the same
        matched_names = set(updt_names) & set(init_names)
        self.assertEqual(num_updates_expected_on_updt, len(matched_names))

        # test that the appropriate number of new instances are created
        self.assertEqual(num_creates_expected_on_updt,
                         len(set(updt_names) - set(init_names)))

        # test that the appropriate number of instances are deleted
        self.assertEqual(num_deletes_expected_on_updt,
                         len(set(init_names) - set(updt_names)))

        # test that the older instances are the ones being deleted
        if num_deletes_expected_on_updt > 0:
            deletes_expected = init_names[:num_deletes_expected_on_updt]
            self.assertNotIn(deletes_expected, updt_names)

        # test if instances are updated
        if update_replace:
            # test that the image id is changed for all instances
            updt_images = [(i.name, i.t['Properties']['ImageId'])
                           for i in updt_instances]
            self.assertEqual(0, len(set(updt_images) & set(init_images)))
        else:
            # test that instance type is changed for all instances
            updt_flavors = [(i.name, i.t['Properties']['InstanceType'])
                            for i in updt_instances]
            self.assertEqual(0, len(set(updt_flavors) & set(init_flavors)))

    def test_instance_group_update_replace(self):
        """
        Test simple update replace with no conflict in batch size and
        minimum instances in service.
        """
        updt_template = json.loads(ig_tmpl_with_updt_policy)
        grp = updt_template['Resources']['JobServerGroup']
        policy = grp['UpdatePolicy']['RollingUpdate']
        policy['MinInstancesInService'] = '1'
        policy['MaxBatchSize'] = '3'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['ImageId'] = 'bar'

        self.update_instance_group(ig_tmpl_with_updt_policy,
                                   json.dumps(updt_template),
                                   num_updates_expected_on_updt=10,
                                   num_creates_expected_on_updt=0,
                                   num_deletes_expected_on_updt=0,
                                   update_replace=True)

    def test_instance_group_update_replace_with_adjusted_capacity(self):
        """
        Test update replace with capacity adjustment due to conflict in
        batch size and minimum instances in service.
        """
        updt_template = json.loads(ig_tmpl_with_updt_policy)
        grp = updt_template['Resources']['JobServerGroup']
        policy = grp['UpdatePolicy']['RollingUpdate']
        policy['MinInstancesInService'] = '8'
        policy['MaxBatchSize'] = '4'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['ImageId'] = 'bar'

        self.update_instance_group(ig_tmpl_with_updt_policy,
                                   json.dumps(updt_template),
                                   num_updates_expected_on_updt=8,
                                   num_creates_expected_on_updt=2,
                                   num_deletes_expected_on_updt=2,
                                   update_replace=True)

    def test_instance_group_update_replace_huge_batch_size(self):
        """
        Test update replace with a huge batch size.
        """
        updt_template = json.loads(ig_tmpl_with_updt_policy)
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['RollingUpdate']
        policy['MinInstancesInService'] = '0'
        policy['MaxBatchSize'] = '20'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['ImageId'] = 'bar'

        self.update_instance_group(ig_tmpl_with_updt_policy,
                                   json.dumps(updt_template),
                                   num_updates_expected_on_updt=10,
                                   num_creates_expected_on_updt=0,
                                   num_deletes_expected_on_updt=0,
                                   update_replace=True)

    def test_instance_group_update_replace_huge_min_in_service(self):
        """
        Test update replace with a huge number of minimum instances in service.
        """
        updt_template = json.loads(ig_tmpl_with_updt_policy)
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['RollingUpdate']
        policy['MinInstancesInService'] = '20'
        policy['MaxBatchSize'] = '1'
        policy['PauseTime'] = 'PT0S'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['ImageId'] = 'bar'

        self.update_instance_group(ig_tmpl_with_updt_policy,
                                   json.dumps(updt_template),
                                   num_updates_expected_on_updt=9,
                                   num_creates_expected_on_updt=1,
                                   num_deletes_expected_on_updt=1,
                                   update_replace=True)

    def test_instance_group_update_no_replace(self):
        """
        Test simple update only and no replace (i.e. updated instance flavor
        in Launch Configuration) with no conflict in batch size and
        minimum instances in service.
        """
        updt_template = json.loads(copy.deepcopy(ig_tmpl_with_updt_policy))
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['RollingUpdate']
        policy['MinInstancesInService'] = '1'
        policy['MaxBatchSize'] = '3'
        policy['PauseTime'] = 'PT0S'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['InstanceType'] = 'm1.large'

        self.update_instance_group(ig_tmpl_with_updt_policy,
                                   json.dumps(updt_template),
                                   num_updates_expected_on_updt=10,
                                   num_creates_expected_on_updt=0,
                                   num_deletes_expected_on_updt=0,
                                   update_replace=False)

    def test_instance_group_update_no_replace_with_adjusted_capacity(self):
        """
        Test update only and no replace (i.e. updated instance flavor in
        Launch Configuration) with capacity adjustment due to conflict in
        batch size and minimum instances in service.
        """
        updt_template = json.loads(copy.deepcopy(ig_tmpl_with_updt_policy))
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['RollingUpdate']
        policy['MinInstancesInService'] = '8'
        policy['MaxBatchSize'] = '4'
        policy['PauseTime'] = 'PT0S'
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['InstanceType'] = 'm1.large'

        self.update_instance_group(ig_tmpl_with_updt_policy,
                                   json.dumps(updt_template),
                                   num_updates_expected_on_updt=8,
                                   num_creates_expected_on_updt=2,
                                   num_deletes_expected_on_updt=2,
                                   update_replace=False)

    def test_instance_group_update_policy_removed(self):

        # setup stack from the initial template
        tmpl = template_format.parse(ig_tmpl_with_updt_policy)
        stack = utils.parse_stack(tmpl)

        # test stack create
        size = int(stack['JobServerGroup'].properties['Size'])
        self._stub_grp_create(size)
        self.m.ReplayAll()
        stack.create()
        self.m.VerifyAll()
        self.assertEqual(('CREATE', 'COMPLETE'), stack.state)

        # test that update policy is loaded
        current_grp = stack['JobServerGroup']
        self.assertIn('RollingUpdate', current_grp.update_policy)
        current_policy = current_grp.update_policy['RollingUpdate']
        self.assertTrue(current_policy)
        self.assertTrue(len(current_policy) > 0)
        init_grp_tmpl = tmpl['Resources']['JobServerGroup']
        init_roll_updt = init_grp_tmpl['UpdatePolicy']['RollingUpdate']
        init_batch_sz = int(init_roll_updt['MaxBatchSize'])
        self.assertEqual(init_batch_sz, int(current_policy['MaxBatchSize']))

        # test that physical resource name of launch configuration is used
        conf = stack['JobServerConfig']
        conf_name_pattern = '%s-JobServerConfig-[a-zA-Z0-9]+$' % stack.name
        self.assertThat(conf.FnGetRefId(), MatchesRegex(conf_name_pattern))

        # test the number of instances created
        nested = stack['JobServerGroup'].nested()
        self.assertEqual(size, len(nested.resources))

        # test stack update
        updated_tmpl = template_format.parse(ig_tmpl_without_updt_policy)
        updated_stack = utils.parse_stack(updated_tmpl)
        stack.update(updated_stack)
        self.assertEqual(('UPDATE', 'COMPLETE'), stack.state)

        # test that update policy is removed
        updated_grp = stack['JobServerGroup']
        self.assertFalse(updated_grp.update_policy['RollingUpdate'])

    def test_instance_group_update_policy_check_timeout(self):

        # setup stack from the initial template
        tmpl = template_format.parse(ig_tmpl_with_updt_policy)
        stack = utils.parse_stack(tmpl)

        # test stack create
        size = int(stack['JobServerGroup'].properties['Size'])
        self._stub_grp_create(size)
        self.m.ReplayAll()
        stack.create()
        self.m.VerifyAll()
        self.assertEqual(('CREATE', 'COMPLETE'), stack.state)

        # test that update policy is loaded
        current_grp = stack['JobServerGroup']
        self.assertIn('RollingUpdate', current_grp.update_policy)
        current_policy = current_grp.update_policy['RollingUpdate']
        self.assertTrue(current_policy)
        self.assertTrue(len(current_policy) > 0)
        init_grp_tmpl = tmpl['Resources']['JobServerGroup']
        init_roll_updt = init_grp_tmpl['UpdatePolicy']['RollingUpdate']
        init_batch_sz = int(init_roll_updt['MaxBatchSize'])
        self.assertEqual(init_batch_sz, int(current_policy['MaxBatchSize']))

        # test the number of instances created
        nested = stack['JobServerGroup'].nested()
        self.assertEqual(size, len(nested.resources))

        # clean up for next test
        self.m.UnsetStubs()

        # modify the pause time and test for error
        new_pause_time = 'PT30M'
        updt_template = json.loads(copy.deepcopy(ig_tmpl_with_updt_policy))
        group = updt_template['Resources']['JobServerGroup']
        policy = group['UpdatePolicy']['RollingUpdate']
        policy['PauseTime'] = new_pause_time
        config = updt_template['Resources']['JobServerConfig']
        config['Properties']['ImageId'] = 'bar'
        updated_tmpl = template_format.parse(json.dumps(updt_template))
        updated_stack = utils.parse_stack(updated_tmpl)
        stack.update(updated_stack)
        self.assertEqual(('UPDATE', 'FAILED'), stack.state)

        # test that the update policy is updated
        updated_grp = stack['JobServerGroup']
        self.assertIn('RollingUpdate', updated_grp.update_policy)
        updated_policy = updated_grp.update_policy['RollingUpdate']
        self.assertTrue(updated_policy)
        self.assertTrue(len(updated_policy) > 0)
        self.assertEqual(new_pause_time, updated_policy['PauseTime'])

        # test that error message match
        expected_error_message = ('The current UpdatePolicy will result '
                                  'in stack update timeout.')
        self.assertIn(expected_error_message, stack.status_reason)
