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


import mox
import uuid
import time
import datetime
import json

import eventlet
import unittest
from nose.plugins.attrib import attr

from oslo.config import cfg

from heat.tests import fakes
from heat.tests.utils import stack_delete_after

import heat.db as db_api
from heat.common import template_format
from heat.common import identifier
from heat.engine import parser
from heat.engine.resources import instance
from heat.common import context

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


@attr(tag=['unit', 'resource', 'Metadata'])
@attr(speed='slow')
class MetadataRefreshTest(unittest.TestCase):
    '''
    The point of the test is to confirm that metadata gets updated
    when FnGetAtt() returns something different.
    gets called.
    '''
    def setUp(self):
        self.m = mox.Mox()
        self.m.StubOutWithMock(eventlet, 'sleep')

        self.fc = fakes.FakeKeystoneClient()

    def tearDown(self):
        self.m.UnsetStubs()

    # Note tests creating a stack should be decorated with @stack_delete_after
    # to ensure the stack is properly cleaned up
    def create_stack(self, stack_name='test_stack',
                     template=test_template_metadata, params={},
                     stub=True):
        temp = template_format.parse(template)
        template = parser.Template(temp)
        parameters = parser.Parameters(stack_name, template, params)
        ctx = context.get_admin_context()
        ctx.tenant_id = 'test_tenant'
        stack = parser.Stack(ctx, stack_name, template, parameters,
                             disable_rollback=True)

        self.stack_id = stack.store()

        if stub:
            self.m.StubOutWithMock(instance.Instance, 'handle_create')
            instance.Instance.handle_create().MultipleTimes().AndReturn(None)
            self.m.StubOutWithMock(instance.Instance, 'FnGetAtt')

        return stack

    @stack_delete_after
    def test_FnGetAtt(self):
        self.stack = self.create_stack()

        instance.Instance.FnGetAtt('PublicIp').AndReturn('1.2.3.5')

        # called by metadata_update()
        instance.Instance.FnGetAtt('PublicIp').AndReturn('10.0.0.5')

        self.m.ReplayAll()
        self.stack.create()

        s1 = self.stack.resources['S1']
        s2 = self.stack.resources['S2']
        files = s1.metadata['AWS::CloudFormation::Init']['config']['files']
        cont = files['/tmp/random_file']['content']
        self.assertEqual(cont, 's2-ip=1.2.3.5')

        s1.metadata_update()
        s2.metadata_update()
        files = s1.metadata['AWS::CloudFormation::Init']['config']['files']
        cont = files['/tmp/random_file']['content']
        self.assertEqual(cont, 's2-ip=10.0.0.5')

        self.m.VerifyAll()
