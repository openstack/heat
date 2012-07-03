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
from heat.engine import instance as instances
from heat.engine import volume as volumes
from heat.engine import manager as managers
import heat.db as db_api
from heat.engine import parser
from heat.engine import auth

test_template_volumeattach = '''
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

test_template_ref = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Parameters" : {

    "KeyName" : {
''' + \
      '"Description" : "Name of an existing EC2' + \
      'KeyPair to enable SSH access to the instances",' + \
'''
      "Type" : "String"
    }
  },

  "Resources" : {
    "WikiDatabase": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId": "image_name",
        "InstanceType": "m1.large",
        "KeyName": { "Ref" : "KeyName" }
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
        "InstanceId" : { "Ref" : "%s" },
        "VolumeId"  : { "Ref" : "DataVolume" },
        "Device" : "/dev/vdb"
      }
    }
  }
}
'''
test_template_findinmap_valid = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Parameters" : {
    "KeyName" : {
''' + \
      '"Description" : "Name of an existing EC2 KeyPair to' + \
      'enable SSH access to the instances",' + \
'''
      "Type" : "String"
    }
  },

  "Resources" : {
    "WikiDatabase": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId": "image_name",
        "InstanceType": "m1.large",
        "KeyName": { "Ref" : "KeyName" }
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
        "Device" : "/dev/vdb"
      }
    }
  }
}
'''
test_template_findinmap_invalid = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Parameters" : {

    "KeyName" : {
''' + \
      '"Description" : "Name of an existing EC2 KeyPair to enable SSH ' + \
      'access to the instances",' + \
'''      "Type" : "String"
    }
  },

  "Mappings" : {
    "AWSInstanceType2Arch" : {
      "t1.micro"    : { "Arch" : "64" },
      "m1.small"    : { "Arch" : "64" },
      "m1.medium"   : { "Arch" : "64" },
      "m1.large"    : { "Arch" : "64" },
      "m1.xlarge"   : { "Arch" : "64" },
      "m2.xlarge"   : { "Arch" : "64" },
      "m2.2xlarge"  : { "Arch" : "64" },
      "m2.4xlarge"  : { "Arch" : "64" },
      "c1.medium"   : { "Arch" : "64" },
      "c1.xlarge"   : { "Arch" : "64" },
      "cc1.4xlarge" : { "Arch" : "64HVM" },
      "cc2.8xlarge" : { "Arch" : "64HVM" },
      "cg1.4xlarge" : { "Arch" : "64HVM" }
    }
  },
  "Resources" : {
    "WikiDatabase": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
''' + \
        '"ImageId" : { "Fn::FindInMap" : [ "DistroArch2AMI", { "Ref" : ' + \
        '"LinuxDistribution" },' + \
        '{ "Fn::FindInMap" : [ "AWSInstanceType2Arch", { "Ref" : ' + \
        '"InstanceType" }, "Arch" ] } ] },' + \
'''
        "InstanceType": "m1.large",
        "KeyName": { "Ref" : "KeyName"}
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
        "Device" : "/dev/vdb"
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
        t = json.loads(test_template_volumeattach % 'vdq')
        self.m.StubOutWithMock(auth, 'authenticate')
        auth.authenticate(None).AndReturn(True)
        stack = parser.Stack(None, 'test_stack', parser.Template(t))

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = stack.resources['MountPoint']
        self.assertTrue(volumeattach.validate() is None)

    def test_validate_volumeattach_invalid(self):
        t = json.loads(test_template_volumeattach % 'sda')
        self.m.StubOutWithMock(auth, 'authenticate')
        auth.authenticate(None).AndReturn(True)
        stack = parser.Stack(None, 'test_stack', parser.Template(t))

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = stack.resources['MountPoint']
        self.assertTrue(volumeattach.validate())

    def test_validate_ref_valid(self):
        t = json.loads(test_template_ref % 'WikiDatabase')
        t['Parameters']['KeyName']['Value'] = 'test'
        params = {}
        self.m.StubOutWithMock(auth, 'authenticate')
        auth.authenticate(None).AndReturn(True)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        manager = managers.EngineManager()
        res = dict(manager.
            validate_template(None, t, params)['ValidateTemplateResult'])
        print 'res %s' % res
        self.assertEqual(res['Description'], 'Successfully validated')

    def test_validate_ref_invalid(self):
        t = json.loads(test_template_ref % 'WikiDatabasez')
        t['Parameters']['KeyName']['Value'] = 'test'
        params = {}
        self.m.StubOutWithMock(auth, 'authenticate')
        auth.authenticate(None).AndReturn(True)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        manager = managers.EngineManager()
        res = dict(manager.
            validate_template(None, t, params)['ValidateTemplateResult'])
        self.assertNotEqual(res['Description'], 'Successfully validated')

    def test_validate_findinmap_valid(self):
        t = json.loads(test_template_findinmap_valid)
        t['Parameters']['KeyName']['Value'] = 'test'
        params = {}
        self.m.StubOutWithMock(auth, 'authenticate')
        auth.authenticate(None).AndReturn(True)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        manager = managers.EngineManager()
        res = dict(manager.
            validate_template(None, t, params)['ValidateTemplateResult'])
        self.assertEqual(res['Description'], 'Successfully validated')

    def test_validate_findinmap_invalid(self):
        t = json.loads(test_template_findinmap_invalid)
        t['Parameters']['KeyName']['Value'] = 'test'
        params = {}
        self.m.StubOutWithMock(auth, 'authenticate')
        auth.authenticate(None).AndReturn(True)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        manager = managers.EngineManager()
        res = dict(manager.
            validate_template(None, t, params)['ValidateTemplateResult'])
        self.assertNotEqual(res['Description'], 'Successfully validated')

    # allows testing of the test directly, shown below
    if __name__ == '__main__':
        sys.argv.append(__file__)
        nose.main()
