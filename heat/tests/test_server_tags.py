
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
import uuid

import mox

from heat.common import template_format
from heat.engine import clients
from heat.engine import environment
from heat.engine import parser
from heat.engine.resources import instance as instances
from heat.engine.resources import nova_utils
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


instance_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"      : "CentOS 5.2",
        "InstanceType" : "256 MB Server",
        "KeyName"      : "test",
        "UserData"     : "wordpress"
      }
    }
  }
}
'''

group_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "Config": {
      "Type": "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"      : "CentOS 5.2",
        "InstanceType" : "256 MB Server",
        "KeyName"      : "test",
        "UserData"     : "wordpress"
      }
    },

    "WebServer": {
      "Type": "OS::Heat::InstanceGroup",
      "Properties": {
        "AvailabilityZones"      : ["nova"],
        "LaunchConfigurationName": { "Ref": "Config" },
        "Size"                   : "1"
      }
    }
  }
}
'''

autoscaling_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "Config": {
      "Type": "AWS::AutoScaling::LaunchConfiguration",
      "Properties": {
        "ImageId"      : "CentOS 5.2",
        "InstanceType" : "256 MB Server",
        "KeyName"      : "test",
        "UserData"     : "wordpress"
      }
    },

    "WebServer": {
      "Type": "AWS::AutoScaling::AutoScalingGroup",
      "Properties": {
        "AvailabilityZones"      : ["nova"],
        "LaunchConfigurationName": { "Ref": "Config" },
        "MinSize"                : "1",
        "MaxSize"                : "2",
        "Tags"                   : [{"Key" : "foo", "Value" : "42"}],
      }
    }
  }
}
'''


class ServerTagsTest(HeatTestCase):
    def setUp(self):
        super(ServerTagsTest, self).setUp()
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()

    def _setup_test_instance(self, intags=None, nova_tags=None):
        stack_name = 'tag_test'
        t = template_format.parse(instance_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment({'KeyName': 'test'}),
                             stack_id=str(uuid.uuid4()))

        t['Resources']['WebServer']['Properties']['Tags'] = intags
        instance = instances.Instance(stack_name,
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        instance.t = instance.stack.resolve_runtime_data(instance.t)

        # need to resolve the template functions
        server_userdata = nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user')
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user').AndReturn(server_userdata)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None,
            meta=nova_tags, nics=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])

        return instance

    def test_instance_tags(self):
        tags = [{'Key': 'Food', 'Value': 'yum'}]
        metadata = dict((tm['Key'], tm['Value']) for tm in tags)

        instance = self._setup_test_instance(intags=tags, nova_tags=metadata)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        # we are just using mock to verify that the tags get through to the
        # nova call.
        self.m.VerifyAll()

    def test_instance_tags_updated(self):
        tags = [{'Key': 'Food', 'Value': 'yum'}]
        metadata = dict((tm['Key'], tm['Value']) for tm in tags)

        instance = self._setup_test_instance(intags=tags, nova_tags=metadata)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        # we are just using mock to verify that the tags get through to the
        # nova call.
        self.m.VerifyAll()
        self.m.UnsetStubs()

        new_tags = [{'Key': 'Food', 'Value': 'yuk'}]
        new_metadata = dict((tm['Key'], tm['Value']) for tm in new_tags)

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc.servers, 'set_meta')
        self.fc.servers.set_meta(self.fc.servers.list()[1],
                                 new_metadata).AndReturn(None)
        self.m.ReplayAll()
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['Tags'] = new_tags
        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def _setup_test_group(self, intags=None, nova_tags=None):
        stack_name = 'tag_test'
        t = template_format.parse(group_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment({'KeyName': 'test'}),
                             stack_id=str(uuid.uuid4()))

        t['Resources']['WebServer']['Properties']['Tags'] = intags

        # create the launch configuration
        conf = stack['Config']
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)

        group = stack['WebServer']

        nova_tags['metering.groupname'] = utils.PhysName(stack.name,
                                                         group.name)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        group.t = group.stack.resolve_runtime_data(group.t)

        # need to resolve the template functions
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=mox.IgnoreArg(),
            security_groups=None,
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=nova_tags, nics=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])

        return group

    def test_group_tags(self):
        tags = [{'Key': 'Food', 'Value': 'yum'}]
        metadata = dict((tm['Key'], tm['Value']) for tm in tags)
        group = self._setup_test_group(intags=tags, nova_tags=metadata)
        self.m.ReplayAll()
        scheduler.TaskRunner(group.create)()
        # we are just using mock to verify that the tags get through to the
        # nova call.
        self.m.VerifyAll()

    def _setup_test_group_autoscaling(self, intags=None, nova_tags=None):
        stack_name = 'tag_as_name'
        t = template_format.parse(autoscaling_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, template,
                             environment.Environment({'KeyName': 'test'}),
                             stack_id=str(uuid.uuid4()))
        t['Resources']['WebServer']['Properties']['Tags'] += intags

        # create the launch configuration
        conf = stack['Config']
        self.assertIsNone(conf.validate())
        scheduler.TaskRunner(conf.create)()
        self.assertEqual((conf.CREATE, conf.COMPLETE), conf.state)
        group = stack['WebServer']

        group_refid = utils.PhysName(stack.name, group.name)

        nova_tags['metering.groupname'] = group_refid
        nova_tags['AutoScalingGroupName'] = group_refid

        self.m.StubOutWithMock(group, '_cooldown_timestamp')
        group._cooldown_timestamp(mox.IgnoreArg()).AndReturn(None)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        group.t = group.stack.resolve_runtime_data(group.t)

        # need to resolve the template functions
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=mox.IgnoreArg(),
            security_groups=None,
            userdata=mox.IgnoreArg(), scheduler_hints=None,
            meta=nova_tags, nics=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])

        return group

    def test_as_group_tags(self):
        tags = [{'Key': 'Food', 'Value': 'yum'}, {'Key': 'foo', 'Value': '42'}]
        metadata = dict((tm['Key'], tm['Value']) for tm in tags)
        group = self._setup_test_group_autoscaling(intags=[tags[0]],
                                                   nova_tags=metadata)
        self.m.ReplayAll()
        scheduler.TaskRunner(group.create)()
        # we are just using mock to verify that the tags get through to the
        # nova call.
        self.m.VerifyAll()
