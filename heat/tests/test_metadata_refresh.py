
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


import mox
from oslo.config import cfg

from heat.common import identifier
from heat.common import template_format
from heat.engine import environment
from heat.engine import parser
from heat.engine.resources import image
from heat.engine.resources import instance
from heat.engine.resources import nova_keypair
from heat.engine.resources import wait_condition as wc
from heat.engine import scheduler
from heat.engine import service
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils


test_template_metadata = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "",
  "Parameters" : {
    "KeyName" : {"Type" : "String", "Default": "mine" },
  },
  "Resources" : {
    "S1": {
      "Type": "AWS::EC2::Instance",
      "Metadata" : {
        "AWS::CloudFormation::Init" : {
          "config" : {
            "files" : {
              "/tmp/random_file" : {
                "content" : { "Fn::Join" : ["", [
                  "s2-ip=", {"Fn::GetAtt": ["S2", "PublicIp"]}
                ]]},
                "mode"    : "000400",
                "owner"   : "root",
                "group"   : "root"
              }
            }
          }
        }
      },
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : "#!/bin/bash -v\n"
      }
    },
    "S2": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : "#!/bin/bash -v\n"
      }
    }
  }
}
'''

test_template_waitcondition = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Just a WaitCondition.",
  "Parameters" : {
    "KeyName" : {"Type" : "String", "Default": "mine" },
  },
  "Resources" : {
    "WH" : {
      "Type" : "AWS::CloudFormation::WaitConditionHandle"
    },
    "S1": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : { "Fn::Join" : [ "", [ "#!/bin/bash -v\n",
                                                "echo ",
                                                { "Ref" : "WH" },
                                                "\n" ] ] }
      }
    },
    "WC" : {
      "Type" : "AWS::CloudFormation::WaitCondition",
      "DependsOn": "S1",
      "Properties" : {
        "Handle" : {"Ref" : "WH"},
        "Timeout" : "5"
      }
    },
    "S2": {
      "Type": "AWS::EC2::Instance",
      "Metadata" : {
        "test" : {"Fn::GetAtt": ["WC", "Data"]}
      },
      "Properties": {
        "ImageId"      : "a",
        "InstanceType" : "m1.large",
        "KeyName"      : { "Ref" : "KeyName" },
        "UserData"     : "#!/bin/bash -v\n"
      }
    }
  }
}
'''


class MetadataRefreshTest(HeatTestCase):
    '''
    The point of the test is to confirm that metadata gets updated
    when FnGetAtt() returns something different.
    gets called.
    '''
    def setUp(self):
        super(MetadataRefreshTest, self).setUp()
        self.fc = fakes.FakeKeystoneClient()
        utils.setup_dummy_db()

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, stack_name='test_stack', params={}):
        temp = template_format.parse(test_template_metadata)
        template = parser.Template(temp)
        ctx = utils.dummy_context()
        stack = parser.Stack(ctx, stack_name, template,
                             environment.Environment(params),
                             disable_rollback=True)

        self.stack_id = stack.store()

        self.m.StubOutWithMock(nova_keypair.KeypairConstraint, 'validate')
        nova_keypair.KeypairConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(image.ImageConstraint, 'validate')
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        for cookie in (object(), object()):
            instance.Instance.handle_create().AndReturn(cookie)
            create_complete = instance.Instance.check_create_complete(cookie)
            create_complete.InAnyOrder().AndReturn(True)
        self.m.StubOutWithMock(instance.Instance, 'FnGetAtt')

        return stack

    @utils.stack_delete_after
    def test_FnGetAtt(self):
        self.stack = self.create_stack()

        instance.Instance.FnGetAtt('PublicIp').AndReturn('1.2.3.5')

        # called by metadata_update()
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.5')

        self.m.ReplayAll()
        self.stack.create()

        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        s1 = self.stack['S1']
        s2 = self.stack['S2']
        files = s1.metadata['AWS::CloudFormation::Init']['config']['files']
        cont = files['/tmp/random_file']['content']
        self.assertEqual((s2.CREATE, s2.COMPLETE), s2.state)
        self.assertEqual('s2-ip=1.2.3.5', cont)

        s1.metadata_update()
        s2.metadata_update()
        files = s1.metadata['AWS::CloudFormation::Init']['config']['files']
        cont = files['/tmp/random_file']['content']
        self.assertEqual('s2-ip=10.0.0.5', cont)

        self.m.VerifyAll()


class WaitCondMetadataUpdateTest(HeatTestCase):
    def setUp(self):
        super(WaitCondMetadataUpdateTest, self).setUp()
        utils.setup_dummy_db()
        self.fc = fakes.FakeKeystoneClient()

        self.m.StubOutWithMock(service.EngineListener, 'start')
        service.EngineListener.start().AndReturn(None)
        self.m.ReplayAll()
        self.man = service.EngineService('a-host', 'a-topic')
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, stack_name='test_stack'):
        temp = template_format.parse(test_template_waitcondition)
        template = parser.Template(temp)
        ctx = utils.dummy_context()
        stack = parser.Stack(ctx, stack_name, template, disable_rollback=True)

        self.stack_id = stack.store()

        self.m.StubOutWithMock(nova_keypair.KeypairConstraint, 'validate')
        nova_keypair.KeypairConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)
        self.m.StubOutWithMock(image.ImageConstraint, 'validate')
        image.ImageConstraint.validate(
            mox.IgnoreArg(), mox.IgnoreArg()).MultipleTimes().AndReturn(True)

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        for cookie in (object(), object()):
            instance.Instance.handle_create().AndReturn(cookie)
            instance.Instance.check_create_complete(cookie).AndReturn(True)

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
        wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(self.fc)

        id = identifier.ResourceIdentifier('test_tenant_id', stack.name,
                                           stack.id, '', 'WH')
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'identifier')
        wc.WaitConditionHandle.identifier().MultipleTimes().AndReturn(id)

        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        self.m.StubOutWithMock(service.EngineService, 'load_user_creds')
        service.EngineService.load_user_creds(
            mox.IgnoreArg()).MultipleTimes().AndReturn(ctx)

        return stack

    @utils.stack_delete_after
    def test_wait_meta(self):
        '''
        1 create stack
        2 assert empty instance metadata
        3 service.metadata_update()
        4 assert valid waitcond metadata
        5 assert valid instance metadata
        '''

        self.stack = self.create_stack()

        watch = self.stack['WC']
        inst = self.stack['S2']

        def check_empty(sleep_time):
            self.assertEqual('{}', watch.FnGetAtt('Data'))
            self.assertIsNone(inst.metadata['test'])

        def update_metadata(id, data, reason):
            self.man.metadata_update(utils.dummy_context(),
                                     dict(self.stack.identifier()),
                                     'WH',
                                     {'Data': data, 'Reason': reason,
                                      'Status': 'SUCCESS', 'UniqueId': id})

        def post_success(sleep_time):
            update_metadata('123', 'foo', 'bar')

        scheduler.TaskRunner._sleep(mox.IsA(int)).WithSideEffects(check_empty)
        scheduler.TaskRunner._sleep(mox.IsA(int)).WithSideEffects(post_success)
        scheduler.TaskRunner._sleep(mox.IsA(int)).MultipleTimes().AndReturn(
            None)

        self.m.ReplayAll()
        self.stack.create()

        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        self.assertEqual('{"123": "foo"}', watch.FnGetAtt('Data'))
        self.assertEqual('{"123": "foo"}', inst.metadata['test'])

        update_metadata('456', 'blarg', 'wibble')
        self.assertEqual('{"123": "foo", "456": "blarg"}',
                         watch.FnGetAtt('Data'))
        self.assertEqual('{"123": "foo", "456": "blarg"}',
                         inst.metadata['test'])

        self.m.VerifyAll()
