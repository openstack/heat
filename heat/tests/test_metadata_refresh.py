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


import mox
from oslo.config import cfg

from heat.common import identifier
from heat.common import template_format
from heat.engine import environment
from heat.engine import parser
from heat.engine.resources import instance
from heat.engine.resources import server
from heat.engine.resources import wait_condition as wc
from heat.engine import scheduler
from heat.engine import service
from heat.tests.common import HeatTestCase
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


test_template_server = '''
heat_template_version: 2013-05-23
resources:
  instance1:
    type: OS::Nova::Server
    metadata: {"template_data": {get_attr: [instance2, first_address]}}
    properties:
      image: cirros-0.3.2-x86_64-disk
      flavor: m1.small
      key_name: stack_key
  instance2:
    type: OS::Nova::Server
    metadata: {'apples': 'pears'}
    properties:
      image: cirros-0.3.2-x86_64-disk
      flavor: m1.small
      key_name: stack_key
'''


class MetadataRefreshTest(HeatTestCase):
    '''
    The point of the test is to confirm that metadata gets updated
    when FnGetAtt() returns something different.
    '''
    def setUp(self):
        super(MetadataRefreshTest, self).setUp()
        self.stub_keystoneclient()

    def create_stack(self, stack_name='test_stack', params=None):
        params = params or {}
        temp = template_format.parse(test_template_metadata)
        template = parser.Template(temp)
        ctx = utils.dummy_context()
        stack = parser.Stack(ctx, stack_name, template,
                             environment.Environment(params),
                             disable_rollback=True)

        self.stack_id = stack.store()

        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        for cookie in (object(), object()):
            instance.Instance.handle_create().AndReturn(cookie)
            create_complete = instance.Instance.check_create_complete(cookie)
            create_complete.InAnyOrder().AndReturn(True)
        self.m.StubOutWithMock(instance.Instance, 'FnGetAtt')

        return stack

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
        files = s1.metadata_get()[
            'AWS::CloudFormation::Init']['config']['files']
        cont = files['/tmp/random_file']['content']
        self.assertEqual((s2.CREATE, s2.COMPLETE), s2.state)
        self.assertEqual('s2-ip=1.2.3.5', cont)

        s1.metadata_update()
        s2.metadata_update()
        files = s1.metadata_get()[
            'AWS::CloudFormation::Init']['config']['files']
        cont = files['/tmp/random_file']['content']
        self.assertEqual('s2-ip=10.0.0.5', cont)

        self.m.VerifyAll()


class WaitCondMetadataUpdateTest(HeatTestCase):
    def setUp(self):
        super(WaitCondMetadataUpdateTest, self).setUp()
        self.stub_keystoneclient()
        self.patch('heat.engine.service.warnings')

        self.man = service.EngineService('a-host', 'a-topic')
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')

    def create_stack(self, stack_name='test_stack'):
        temp = template_format.parse(test_template_waitcondition)
        template = parser.Template(temp)
        ctx = utils.dummy_context()
        stack = parser.Stack(ctx, stack_name, template, disable_rollback=True)

        self.stack_id = stack.store()

        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()

        self.m.StubOutWithMock(instance.Instance, 'handle_create')
        self.m.StubOutWithMock(instance.Instance, 'check_create_complete')
        for cookie in (object(), object()):
            instance.Instance.handle_create().AndReturn(cookie)
            instance.Instance.check_create_complete(cookie).AndReturn(True)

        id = identifier.ResourceIdentifier('test_tenant_id', stack.name,
                                           stack.id, '', 'WH')
        self.m.StubOutWithMock(wc.WaitConditionHandle, 'identifier')
        wc.WaitConditionHandle.identifier().MultipleTimes().AndReturn(id)

        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        return stack

    def test_wait_meta(self):
        '''
        1 create stack
        2 assert empty instance metadata
        3 service.resource_signal()
        4 assert valid waitcond metadata
        5 assert valid instance metadata
        '''
        self.stack = self.create_stack()

        watch = self.stack['WC']
        inst = self.stack['S2']

        def check_empty(sleep_time):
            self.assertEqual('{}', watch.FnGetAtt('Data'))
            self.assertIsNone(inst.metadata_get()['test'])

        def update_metadata(id, data, reason):
            self.man.resource_signal(utils.dummy_context(),
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
        self.assertEqual('{"123": "foo"}', inst.metadata_get()['test'])

        update_metadata('456', 'blarg', 'wibble')
        self.assertEqual('{"123": "foo", "456": "blarg"}',
                         watch.FnGetAtt('Data'))
        self.assertEqual('{"123": "foo"}',
                         inst.metadata_get()['test'])
        self.assertEqual('{"123": "foo", "456": "blarg"}',
                         inst.metadata_get(refresh=True)['test'])

        self.m.VerifyAll()


class MetadataRefreshTestServer(HeatTestCase):
    '''
    The point of the test is to confirm that metadata gets updated
    when FnGetAtt() returns something different when using a native
    OS::Nova::Server resource, and that metadata keys set inside the
    resource (as opposed to in the template), e.g for deployments, don't
    get overwritten on update/refresh.
    '''
    def setUp(self):
        super(MetadataRefreshTestServer, self).setUp()
        self.stub_keystoneclient()

    def create_stack(self, stack_name='test_stack_native', params=None):
        params = params or {}
        temp = template_format.parse(test_template_server)
        template = parser.Template(temp)
        ctx = utils.dummy_context()
        stack = parser.Stack(ctx, stack_name, template,
                             environment.Environment(params),
                             disable_rollback=True)

        self.stack_id = stack.store()

        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()

        self.m.StubOutWithMock(server.Server, 'handle_create')
        self.m.StubOutWithMock(server.Server, 'check_create_complete')
        for cookie in (object(), object()):
            server.Server.handle_create().AndReturn(cookie)
            create_complete = server.Server.check_create_complete(cookie)
            create_complete.InAnyOrder().AndReturn(True)
        self.m.StubOutWithMock(server.Server, 'FnGetAtt')

        return stack

    def test_FnGetAtt(self):
        self.stack = self.create_stack()

        # Note dummy addresses are from TEST-NET-1 ref rfc5737
        server.Server.FnGetAtt('first_address').AndReturn('192.0.2.1')

        # called by metadata_update()
        server.Server.FnGetAtt('first_address').AndReturn('192.0.2.2')
        server.Server.FnGetAtt('first_address').AndReturn('192.0.2.2')

        self.m.ReplayAll()
        self.stack.create()

        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)

        s1 = self.stack['instance1']
        s2 = self.stack['instance2']
        md = s1.metadata_get()
        self.assertEqual({u'template_data': '192.0.2.1'}, md)

        s1.metadata_update()
        s2.metadata_update()
        md = s1.metadata_get()
        self.assertEqual({u'template_data': '192.0.2.2'}, md)

        # Now set some metadata via the resource, like is done by
        # _populate_deployments_metadata.  This should be persisted over
        # calls to metadata_update()
        new_md = {u'template_data': '192.0.2.2', 'set_by_rsrc': 'orange'}
        s1.metadata_set(new_md)
        md = s1.metadata_get(refresh=True)
        self.assertEqual(new_md, md)
        s1.metadata_update()
        md = s1.metadata_get(refresh=True)
        self.assertEqual(new_md, md)

        self.m.VerifyAll()
