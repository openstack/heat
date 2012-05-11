import sys
import os

import nose
import unittest
import mox
import json
import sqlalchemy

from nose.plugins.attrib import attr
from nose import with_setup

from heat.tests.v1_1 import fakes
from heat.engine import volume as volumes
import heat.db as db_api
from heat.engine import parser

test_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Resources" : {
    "WikiDatabase": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId": "image_name",
        "InstanceType": "m1.large",
        "KeyName": "test_KeyName"
      }
    },
    "DataVolume" : {
      "Type" : "AWS::EC2::Volume",
      "Properties" : {
        "Size" : "6",
        "AvailabilityZone" : "nova"
      }
    },
    "MountPoint" : {
      "Type" : "AWS::EC2::VolumeAttachment",
      "Properties" : {
        "InstanceId" : { "Ref" : "WikiDatabase" },
        "VolumeId"  : { "Ref" : "DataVolume" },
        "Device" : "/dev/%s"
      }
    }
  }
}
'''
@attr(tag=['unit', 'validate'])
@attr(speed='fast')
class validateTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()

    def tearDown(self):
        self.m.UnsetStubs()
        print "volumeTest teardown complete"

    def test_validate_volumeattach_valid(self):
        t = json.loads(test_template % 'vdq')
        params = {}
        params['KeyStoneCreds'] = None
        stack = parser.Stack('test_stack', t, 0, params)

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',\
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = stack.resources['MountPoint']
        stack.resolve_attributes(volumeattach.t)
        stack.resolve_joins(volumeattach.t)
        stack.resolve_base64(volumeattach.t)
        assert(volumeattach.validate() == None)

    def test_validate_volumeattach_invalid(self):
        t = json.loads(test_template % 'sda')
        params = {}
        params['KeyStoneCreds'] = None
        stack = parser.Stack('test_stack', t, 0, params)

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',\
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = stack.resources['MountPoint']
        stack.resolve_attributes(volumeattach.t)
        stack.resolve_joins(volumeattach.t)
        stack.resolve_base64(volumeattach.t)
        assert(volumeattach.validate())

    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
