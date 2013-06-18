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

from testtools import skipIf

from heat.engine import environment
from heat.tests.v1_1 import fakes
from heat.common import exception
from heat.common import template_format
from heat.engine import resources
from heat.engine.resources import instance as instances
from heat.engine import service
from heat.openstack.common.importutils import try_import
import heat.db.api as db_api
from heat.engine import parser
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db

test_template_volumeattach = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Resources" : {
    "WikiDatabase": {
      "Type": "AWS::EC2::Instance",
      "DeletionPolicy": "Delete",
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

test_template_invalid_property = '''
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
            "KeyName": { "Ref" : "KeyName" },
            "UnknownProperty": "unknown"
          }
        }
      }
    }
    '''

test_template_unimplemented_property = '''
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
            "KeyName": { "Ref" : "KeyName" },
            "SourceDestCheck": "false"
          }
        }
      }
    }
    '''

test_template_invalid_deletion_policy = '''
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
          "DeletionPolicy": "Destroy",
          "Properties": {
            "ImageId": "image_name",
            "InstanceType": "m1.large",
            "KeyName": { "Ref" : "KeyName" }
          }
        }
      }
    }
    '''

test_template_snapshot_deletion_policy = '''
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
          "DeletionPolicy": "Snapshot",
          "Properties": {
            "ImageId": "image_name",
            "InstanceType": "m1.large",
            "KeyName": { "Ref" : "KeyName" }
          }
        }
      }
    }
    '''

test_template_volume_snapshot = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Resources" : {
    "DataVolume" : {
      "Type" : "AWS::EC2::Volume",
      "DeletionPolicy": "Snapshot",
      "Properties" : {
        "Size" : "6",
        "AvailabilityZone" : "nova"
      }
    }
  }
}
'''

test_unregistered_key = '''
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
        "Instance": {
          "Type": "AWS::EC2::Instance",
          "Properties": {
            "ImageId": "image_name",
            "InstanceType": "m1.large",
            "KeyName": { "Ref" : "KeyName" }
          }
        }
      }
    }
    '''

test_template_invalid_secgroups = '''
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
        "Instance": {
          "Type": "AWS::EC2::Instance",
          "Properties": {
            "ImageId": "image_name",
            "InstanceType": "m1.large",
            "KeyName": { "Ref" : "KeyName" },
            "SecurityGroups": [ "default" ],
            "NetworkInterfaces": [ "mgmt", "data" ]
          }
        }
      }
    }
    '''

test_template_invalid_secgroupids = '''
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
        "Instance": {
          "Type": "AWS::EC2::Instance",
          "Properties": {
            "ImageId": "image_name",
            "InstanceType": "m1.large",
            "KeyName": { "Ref" : "KeyName" },
            "SecurityGroupIds": [ "default" ],
            "NetworkInterfaces": [ "mgmt", "data" ]
          }
        }
      }
    }
    '''


class validateTest(HeatTestCase):
    def setUp(self):
        super(validateTest, self).setUp()
        resources.initialise()
        self.fc = fakes.FakeClient()
        resources.initialise()
        setup_dummy_db()

    def test_validate_volumeattach_valid(self):
        t = template_format.parse(test_template_volumeattach % 'vdq')
        stack = parser.Stack(None, 'test_stack', parser.Template(t))

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = stack.resources['MountPoint']
        self.assertTrue(volumeattach.validate() is None)

    def test_validate_volumeattach_invalid(self):
        t = template_format.parse(test_template_volumeattach % 'sda')
        stack = parser.Stack(None, 'test_stack', parser.Template(t))

        self.m.StubOutWithMock(db_api, 'resource_get_by_name_and_stack')
        db_api.resource_get_by_name_and_stack(None, 'test_resource_name',
                                              stack).AndReturn(None)

        self.m.ReplayAll()
        volumeattach = stack.resources['MountPoint']
        self.assertRaises(exception.StackValidationFailed,
                          volumeattach.validate)

    def test_validate_ref_valid(self):
        t = template_format.parse(test_template_ref % 'WikiDatabase')

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(res['Description'], 'test.')

    def test_validate_ref_invalid(self):
        t = template_format.parse(test_template_ref % 'WikiDatabasez')

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertNotEqual(res['Description'], 'Successfully validated')

    def test_validate_findinmap_valid(self):
        t = template_format.parse(test_template_findinmap_valid)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(res['Description'], 'test.')

    def test_validate_findinmap_invalid(self):
        t = template_format.parse(test_template_findinmap_invalid)

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertNotEqual(res['Description'], 'Successfully validated')

    def test_validate_parameters(self):
        t = template_format.parse(test_template_ref % 'WikiDatabase')

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(res['Parameters'], {'KeyName': {
            'Type': 'String',
            'Description': 'Name of an existing EC2KeyPair to enable SSH '
                           'access to the instances'}})

    def test_validate_properties(self):
        t = template_format.parse(test_template_invalid_property)
        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(res, {'Error': 'Unknown Property UnknownProperty'})

    def test_unimplemented_property(self):
        t = template_format.parse(test_template_unimplemented_property)
        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(
            res,
            {'Error': 'Property SourceDestCheck not implemented yet'})

    def test_invalid_deletion_policy(self):
        t = template_format.parse(test_template_invalid_deletion_policy)
        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(res, {'Error': 'Invalid DeletionPolicy Destroy'})

    def test_snapshot_deletion_policy(self):
        t = template_format.parse(test_template_snapshot_deletion_policy)
        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(
            res, {'Error': 'Snapshot DeletionPolicy not supported'})

    @skipIf(try_import('cinderclient.v1.volume_backups') is None,
            'unable to import volume_backups')
    def test_volume_snapshot_deletion_policy(self):
        t = template_format.parse(test_template_volume_snapshot)
        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual(res, {'Description': u'test.', 'Parameters': {}})

    def test_unregistered_key(self):
        t = template_format.parse(test_unregistered_key)
        template = parser.Template(t)
        params = {'KeyName': 'not_registered'}
        stack = parser.Stack(None, 'test_stack', template,
                             environment.Environment(params))

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        resource = stack.resources['Instance']
        self.assertNotEqual(resource.validate(), None)

    def test_invalid_security_groups_with_nics(self):
        t = template_format.parse(test_template_invalid_secgroups)
        template = parser.Template(t)
        stack = parser.Stack(None, 'test_stack', template,
                             environment.Environment({'KeyName': 'test'}))

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        resource = stack.resources['Instance']
        self.assertNotEqual(resource.validate(), None)

    def test_invalid_security_group_ids_with_nics(self):
        t = template_format.parse(test_template_invalid_secgroupids)
        template = parser.Template(t)
        stack = parser.Stack(None, 'test_stack', template,
                             environment.Environment({'KeyName': 'test'}))

        self.m.StubOutWithMock(instances.Instance, 'nova')
        instances.Instance.nova().AndReturn(self.fc)
        self.m.ReplayAll()

        resource = stack.resources['Instance']
        self.assertNotEqual(resource.validate(), None)
