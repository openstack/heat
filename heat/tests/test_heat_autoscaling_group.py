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
import datetime

from oslo.config import cfg

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import resource
from heat.engine import scheduler
from heat.openstack.common import timeutils
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import generic_resource
from heat.tests import utils


class AutoScalingGroupTest(HeatTestCase):

    as_template = '''
        heat_template_version: 2013-05-23
        description: AutoScaling Test
        resources:
          my-group:
            properties:
              max_size: 5
              min_size: 1
              resource:
                type: ResourceWithProps
                properties:
                    Foo: hello
            type: OS::Heat::AutoScalingGroup
    '''

    def setUp(self):
        super(AutoScalingGroupTest, self).setUp()
        utils.setup_dummy_db()
        resource._register_class('ResourceWithProps',
                                 generic_resource.ResourceWithProps)
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.fc = fakes.FakeKeystoneClient()
        client = self.patchobject(clients.OpenStackClients, "keystone")
        client.return_value = self.fc
        self.parsed = template_format.parse(self.as_template)

    def create_stack(self, t):
        stack = utils.parse_stack(t)
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        return stack

    def test_scaling_delete_empty(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 0
        properties['max_size'] = 0
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(0, len(rsrc.get_instances()))
        rsrc.delete()

    def test_scaling_adjust_down_empty(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 1
        rsrc = self.create_stack(self.parsed)['my-group']
        resources = rsrc.get_instances()
        self.assertEqual(1, len(resources))

        # Reduce the min size to 0, should complete without adjusting
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['min_size'] = 0
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(resources, rsrc.get_instances())

        # trigger adjustment to reduce to 0, there should be no more instances
        rsrc.adjust(-1)
        self.assertEqual(0, len(rsrc.get_instances()))

    def test_scaling_group_update_replace(self):
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, len(rsrc.get_instances()))
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        props = update_snippet['Properties']['resource']['properties']
        props['Foo'] = 'Bar'
        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        self.assertRaises(resource.UpdateReplace, updater)

    def test_scaling_group_suspend(self):
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, len(rsrc.get_instances()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)

    def test_scaling_group_resume(self):
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, len(rsrc.get_instances()))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        for i in rsrc.nested().values():
            i.state_set(rsrc.SUSPEND, rsrc.COMPLETE)

        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

    def test_scaling_group_create_error(self):
        mock_create = self.patchobject(generic_resource.ResourceWithProps,
                                       'handle_create')
        mock_create.side_effect = Exception("Creation failed!")

        rsrc = utils.parse_stack(self.parsed)['my-group']

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.assertEqual(0, len(rsrc.get_instances()))

    def test_scaling_group_update_ok_maxsize(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 3

        rsrc = self.create_stack(self.parsed)['my-group']
        resources = rsrc.get_instances()
        self.assertEqual(1, len(resources))

        # Reduce the max size to 2, should complete without adjusting
        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['max_size'] = 2
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(resources, rsrc.get_instances())
        self.assertEqual(2, rsrc.properties['max_size'])

    def test_scaling_group_update_ok_minsize(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 3

        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, len(rsrc.get_instances()))

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['min_size'] = 2
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(2, len(rsrc.get_instances()))
        self.assertEqual(2, rsrc.properties['min_size'])

    def test_scaling_group_update_ok_desired(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 3
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, len(rsrc.get_instances()))

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['desired_capacity'] = 2
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(2, len(rsrc.get_instances()))
        self.assertEqual(2, rsrc.properties['desired_capacity'])

    def test_scaling_group_update_ok_desired_remove(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['desired_capacity'] = 2
        rsrc = self.create_stack(self.parsed)['my-group']
        resources = rsrc.get_instances()
        self.assertEqual(2, len(resources))

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties'].pop('desired_capacity')
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(resources, rsrc.get_instances())
        self.assertIsNone(rsrc.properties['desired_capacity'])

    def test_scaling_group_scale_up_failure(self):
        stack = self.create_stack(self.parsed)
        mock_create = self.patchobject(generic_resource.ResourceWithProps,
                                       'handle_create')
        rsrc = stack['my-group']
        self.assertEqual(1, len(rsrc.get_instances()))

        mock_create.side_effect = exception.Error('Bang')
        self.assertRaises(exception.Error, rsrc.adjust, 1)
        self.assertEqual(1, len(rsrc.get_instances()))

    def test_scaling_group_truncate_adjustment(self):
        # Create initial group, 2 instances
        properties = self.parsed['resources']['my-group']['properties']
        properties['desired_capacity'] = 2
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(2, len(rsrc.get_instances()))

        rsrc.adjust(4)
        self.assertEqual(5, len(rsrc.get_instances()))

        rsrc.adjust(-5)
        self.assertEqual(1, len(rsrc.get_instances()))

        rsrc.adjust(0)
        self.assertEqual(1, len(rsrc.get_instances()))

    def _do_test_scaling_group_percent(self, decrease, lowest,
                                       increase, create, highest):
        # Create initial group, 2 instances
        properties = self.parsed['resources']['my-group']['properties']
        properties['desired_capacity'] = 2
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(2, len(rsrc.get_instances()))

        # reduce by decrease %
        rsrc.adjust(decrease, 'percentage_change_in_capacity')
        self.assertEqual(lowest, len(rsrc.get_instances()))

        # raise by increase %
        rsrc.adjust(increase, 'percentage_change_in_capacity')
        self.assertEqual(highest, len(rsrc.get_instances()))

    def test_scaling_group_percent(self):
        self._do_test_scaling_group_percent(-50, 1, 200, 2, 3)

    def test_scaling_group_percent_round_up(self):
        self._do_test_scaling_group_percent(-33, 1, 33, 1, 2)

    def test_scaling_group_percent_round_down(self):
        self._do_test_scaling_group_percent(-66, 1, 225, 2, 3)

    def test_min_min_size(self):
        self.parsed['resources']['my-group']['properties']['min_size'] = -1
        stack = utils.parse_stack(self.parsed)
        self.assertRaises(exception.StackValidationFailed,
                          stack['my-group'].validate)

    def test_min_max_size(self):
        self.parsed['resources']['my-group']['properties']['max_size'] = -1
        stack = utils.parse_stack(self.parsed)
        self.assertRaises(exception.StackValidationFailed,
                          stack['my-group'].validate)


class HeatScalingGroupWithCFNScalingPolicyTest(HeatTestCase):
    as_template = '''
        heat_template_version: 2013-05-23
        description: AutoScaling Test
        resources:
          my-group:
            properties:
              max_size: 5
              min_size: 1
              resource:
                type: ResourceWithProps
                properties:
                    Foo: hello
            type: OS::Heat::AutoScalingGroup
          scale-up:
            type: AWS::AutoScaling::ScalingPolicy
            properties:
              AutoScalingGroupName: {get_resource: my-group}
              ScalingAdjustment: 1
              AdjustmentType: ChangeInCapacity
              Cooldown: 60
    '''

    def setUp(self):
        super(HeatScalingGroupWithCFNScalingPolicyTest, self).setUp()
        utils.setup_dummy_db()
        resource._register_class('ResourceWithProps',
                                 generic_resource.ResourceWithProps)
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.fc = fakes.FakeKeystoneClient()
        client = self.patchobject(clients.OpenStackClients, "keystone")
        client.return_value = self.fc
        self.parsed = template_format.parse(self.as_template)

    def create_stack(self, t):
        stack = utils.parse_stack(t)
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        return stack

    def test_scale_up(self):
        stack = self.create_stack(self.parsed)
        scale_up = stack['scale-up']
        group = stack['my-group']
        self.assertEqual(1, len(group.get_instances()))
        scale_up.signal()
        self.assertEqual(2, len(group.get_instances()))

    def test_no_instance_list(self):
        """
        The InstanceList attribute is not inherited from
        AutoScalingResourceGroup's superclasses.
        """
        stack = self.create_stack(self.parsed)
        group = stack['my-group']
        self.assertRaises(exception.InvalidTemplateAttribute,
                          group.FnGetAtt, 'InstanceList')


class ScalingPolicyTest(HeatTestCase):

    as_template = '''
        heat_template_version: 2013-05-23
        resources:
          my-policy:
            type: OS::Heat::ScalingPolicy
            properties:
                auto_scaling_group_id: {get_resource: my-group}
                adjustment_type: change_in_capacity
                scaling_adjustment: 1
          my-group:
            type: OS::Heat::AutoScalingGroup
            properties:
              max_size: 5
              min_size: 1
              resource:
                type: ResourceWithProps
                properties:
                    Foo: hello
    '''

    def setUp(self):
        super(ScalingPolicyTest, self).setUp()
        utils.setup_dummy_db()
        resource._register_class('ResourceWithProps',
                                 generic_resource.ResourceWithProps)
        self.fc = fakes.FakeKeystoneClient()
        client = self.patchobject(clients.OpenStackClients, "keystone")
        client.return_value = self.fc
        self.parsed = template_format.parse(self.as_template)

    def test_alarm_attribute(self):
        stack = utils.parse_stack(self.parsed)
        stack.create()
        policy = stack['my-policy']
        self.assertIn("my-policy", policy.FnGetAtt('alarm_url'))

    def test_signal(self):
        stack = utils.parse_stack(self.parsed)
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        policy = stack['my-policy']
        group = stack['my-group']

        self.assertEqual("1234", policy.FnGetRefId())

        self.assertEqual(1, len(group.get_instance_names()))
        policy.signal()
        self.assertEqual(2, len(group.get_instance_names()))

    def test_signal_with_cooldown(self):
        self.parsed['resources']['my-policy']['properties']['cooldown'] = 60
        stack = utils.parse_stack(self.parsed)
        stack.create()
        policy = stack['my-policy']
        group = stack['my-group']

        self.assertEqual(1, len(group.get_instance_names()))
        policy.signal()
        self.assertEqual(2, len(group.get_instance_names()))
        policy.signal()
        # The second signal shouldn't have changed it because of cooldown
        self.assertEqual(2, len(group.get_instance_names()))

        past = timeutils.strtime(timeutils.utcnow() -
                                 datetime.timedelta(seconds=65))
        policy.metadata = {past: 'ChangeInCapacity : 1'}

        policy.signal()
        self.assertEqual(3, len(group.get_instance_names()))
