
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

import mox

from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine import resource
from heat.engine import resources
from heat.engine.resources import image
from heat.engine.resources import instance
from heat.engine.resources import nova_keypair
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils


ig_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to create multiple instances.",
  "Parameters" : {},
  "Resources" : {
    "JobServerGroup" : {
      "Type" : "OS::Heat::InstanceGroup",
      "Properties" : {
        "LaunchConfigurationName" : { "Ref" : "JobServerConfig" },
        "Size" : "1",
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
        utils.setup_dummy_db()

    def _stub_create(self, num, instance_class=instance.Instance):
        """
        Expect creation of C{num} number of Instances.

        :param instance_class: The resource class to expect to be created
                               instead of instance.Instance.
        """
        self.m.StubOutWithMock(parser.Stack, 'validate')
        parser.Stack.validate()
        self.m.StubOutWithMock(nova_keypair.KeypairConstraint, 'validate')
        nova_keypair.KeypairConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(image.ImageConstraint, 'validate')
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

        self.m.StubOutWithMock(instance_class, 'handle_create')
        self.m.StubOutWithMock(instance_class, 'check_create_complete')
        cookie = object()

        for x in range(num):
            instance_class.handle_create().AndReturn(cookie)
        instance_class.check_create_complete(cookie).AndReturn(False)
        instance_class.check_create_complete(
            cookie).MultipleTimes().AndReturn(True)

    def create_resource(self, t, stack, resource_name):
        # subsequent resources may need to reference previous created resources
        # use the stack's resource objects instead of instantiating new ones
        rsrc = stack[resource_name]
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_instance_group(self):

        t = template_format.parse(ig_template)
        stack = utils.parse_stack(t)

        # start with min then delete
        self._stub_create(1)
        self.m.StubOutWithMock(instance.Instance, 'FnGetAtt')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('1.2.3.4')

        self.m.ReplayAll()
        self.create_resource(t, stack, 'JobServerConfig')
        rsrc = self.create_resource(t, stack, 'JobServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        self.assertEqual('1.2.3.4', rsrc.FnGetAtt('InstanceList'))

        nested = rsrc.nested()
        self.assertEqual(nested.id, rsrc.resource_id)

        rsrc.delete()
        self.m.VerifyAll()

    def test_instance_group_custom_resource(self):
        """
        If AWS::EC2::Instance is overridden, InstanceGroup will automatically
        use that overridden resource type.
        """
        # resources may need to be initialised if this is the first test run.
        resources.initialise()

        class MyInstance(instance.Instance):
            """A customized Instance resource."""

        original_instance = resource.get_class("AWS::EC2::Instance")
        resource._register_class("AWS::EC2::Instance", MyInstance)
        self.addCleanup(resource._register_class, "AWS::EC2::Instance",
                        original_instance)

        t = template_format.parse(ig_template)
        stack = utils.parse_stack(t)
        self._stub_create(1, instance_class=MyInstance)

        self.m.ReplayAll()
        self.create_resource(t, stack, 'JobServerConfig')
        rsrc = self.create_resource(t, stack, 'JobServerGroup')
        self.assertEqual(utils.PhysName(stack.name, rsrc.name),
                         rsrc.FnGetRefId())
        rsrc.delete()
        self.m.VerifyAll()

    def test_missing_image(self):

        t = template_format.parse(ig_template)
        stack = utils.parse_stack(t)

        self.create_resource(t, stack, 'JobServerConfig')
        rsrc = stack['JobServerGroup']

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        not_found = exception.ImageNotFound(image_name='bla')
        instance.Instance.handle_create().AndRaise(not_found)
        self.m.StubOutWithMock(parser.Stack, 'validate')
        parser.Stack.validate()
        self.m.StubOutWithMock(nova_keypair.KeypairConstraint, 'validate')
        nova_keypair.KeypairConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(image.ImageConstraint, 'validate')
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

        self.m.ReplayAll()

        create = scheduler.TaskRunner(rsrc.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.m.VerifyAll()

    def test_handle_update_size(self):
        t = template_format.parse(ig_template)
        properties = t['Resources']['JobServerGroup']['Properties']
        properties['Size'] = '2'
        stack = utils.parse_stack(t)

        self._stub_create(2)
        self.m.ReplayAll()
        self.create_resource(t, stack, 'JobServerConfig')
        rsrc = self.create_resource(t, stack, 'JobServerGroup')

        self.m.VerifyAll()
        self.m.UnsetStubs()

        # Increase min size to 5
        self._stub_create(3)
        self.m.StubOutWithMock(instance.Instance, 'FnGetAtt')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.2')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.3')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.4')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.5')
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.6')

        self.m.ReplayAll()

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['Size'] = '5'
        tmpl_diff = {'Properties': {'Size': '5'}}
        prop_diff = {'Size': '5'}
        self.assertIsNone(rsrc.handle_update(update_snippet, tmpl_diff,
                                             prop_diff))
        self.assertEqual('10.0.0.2,10.0.0.3,10.0.0.4,10.0.0.5,10.0.0.6',
                         rsrc.FnGetAtt('InstanceList'))

        rsrc.delete()
        self.m.VerifyAll()

    def test_create_error(self):
        """
        If a resource in an instance group fails to be created, the instance
        group itself will fail and the broken inner resource will remain.
        """
        t = template_format.parse(ig_template)
        stack = utils.parse_stack(t)

        self.m.StubOutWithMock(parser.Stack, 'validate')
        parser.Stack.validate()
        self.m.StubOutWithMock(nova_keypair.KeypairConstraint, 'validate')
        nova_keypair.KeypairConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(image.ImageConstraint, 'validate')
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        instance.Instance.handle_create().AndRaise(Exception)

        self.m.ReplayAll()
        self.create_resource(t, stack, 'JobServerConfig')
        self.assertRaises(
            exception.ResourceFailure,
            self.create_resource, t, stack, 'JobServerGroup')

        rsrc = stack['JobServerGroup']
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        # The failed inner resource remains
        self.assertEqual(1, len(rsrc.nested().resources))
        child_resource = rsrc.nested().resources.values()[0]
        self.assertEqual((child_resource.CREATE, child_resource.FAILED),
                         child_resource.state)

        self.m.VerifyAll()

    def test_update_error(self):
        """
        If a resource in an instance group fails to be created during an
        update, the instance group itself will fail and the broken inner
        resource will remain.
        """
        t = template_format.parse(ig_template)
        stack = utils.parse_stack(t)

        self._stub_create(1)
        self.m.ReplayAll()
        self.create_resource(t, stack, 'JobServerConfig')
        rsrc = self.create_resource(t, stack, 'JobServerGroup')
        self.assertEqual(1, len(rsrc.nested().resources))
        succeeded_instance = rsrc.nested().resources.values()[0]

        self.m.VerifyAll()
        self.m.UnsetStubs()

        self.m.StubOutWithMock(parser.Stack, 'validate')
        parser.Stack.validate()
        self.m.StubOutWithMock(nova_keypair.KeypairConstraint, 'validate')
        nova_keypair.KeypairConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(image.ImageConstraint, 'validate')
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        instance.Instance.handle_create().AndRaise(Exception)

        self.m.ReplayAll()

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['Size'] = '2'
        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        self.assertRaises(exception.ResourceFailure, updater)

        self.assertEqual((rsrc.UPDATE, rsrc.FAILED), rsrc.state)

        # The failed inner resource remains
        self.assertEqual(2, len(rsrc.nested().resources))
        child_resource = [r for r in rsrc.nested().resources.values()
                          if r.name != succeeded_instance.name][0]
        self.assertEqual((child_resource.CREATE, child_resource.FAILED),
                         child_resource.state)

        self.m.VerifyAll()

    def test_update_fail_badkey(self):
        t = template_format.parse(ig_template)
        properties = t['Resources']['JobServerGroup']['Properties']
        properties['Size'] = '2'
        stack = utils.parse_stack(t)

        self._stub_create(2)
        self.m.ReplayAll()
        self.create_resource(t, stack, 'JobServerConfig')
        rsrc = self.create_resource(t, stack, 'JobServerGroup')

        self.m.ReplayAll()

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Metadata'] = 'notallowedforupdate'
        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        self.assertRaises(resource.UpdateReplace, updater)

        rsrc.delete()
        self.m.VerifyAll()

    def test_update_fail_badprop(self):
        t = template_format.parse(ig_template)
        properties = t['Resources']['JobServerGroup']['Properties']
        properties['Size'] = '2'
        stack = utils.parse_stack(t)

        self._stub_create(2)
        self.m.ReplayAll()
        self.create_resource(t, stack, 'JobServerConfig')
        rsrc = self.create_resource(t, stack, 'JobServerGroup')

        self.m.ReplayAll()

        update_snippet = copy.deepcopy(rsrc.parsed_template())
        update_snippet['Properties']['AvailabilityZones'] = ['wibble']
        updater = scheduler.TaskRunner(rsrc.update, update_snippet)
        self.assertRaises(resource.UpdateReplace, updater)

        rsrc.delete()
        self.m.VerifyAll()
