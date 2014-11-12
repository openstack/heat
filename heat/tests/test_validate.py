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

from glanceclient import exc as glance_exceptions
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine.hot.template import HOTemplate20130523
from heat.engine import parser
from heat.engine import resources
from heat.engine import service
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes

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

test_template_invalid_resources = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "AWS CloudFormation Sample Template for xyz.",
   "Parameters" : {
        "InstanceType" : {
            "Description" : "Defined instance type",
            "Type" : "String",
            "Default" : "node.ee",
            "AllowedValues" : ["node.ee", "node.apache", "node.api"],
            "ConstraintDescription" : "must be a valid instance type."
        }
    },
    "Resources" : {
        "Type" : "AWS::EC2::Instance",
        "Metadata" : {
        },
        "Properties" : {
            "ImageId" : { "Ref" : "centos-6.4-20130701-0" },
            "InstanceType" : { "Ref" : "InstanceType" }
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

test_template_image = '''
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

test_template_glance_client_exception = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Resources" : {
    "Instance": {
      "Type": "AWS::EC2::Instance",
      "DeletionPolicy": "Delete",
      "Properties": {
        "ImageId": "image_name",
        "InstanceType": "m1.large"
      }
    }
  }
}
'''

test_template_unique_logical_name = '''
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
        },
    "AName" : {
''' + \
    '"Description" : "Name of an existing EC2' + \
    'KeyPair to enable SSH access to the instances",' + \
    '''
          "Type" : "String"
        }
      },

      "Resources" : {
        "AName": {
          "Type": "AWS::EC2::Instance",
          "Properties": {
            "ImageId": "image_name",
            "InstanceType": "m1.large",
            "KeyName": { "Ref" : "KeyName" },
            "NetworkInterfaces": [ "mgmt", "data" ]
          }
        }
      }
    }
    '''

test_template_cfn_parameter_label = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "test.",
  "Parameters" : {

    "KeyName" : {
''' + \
    '"Description" : "Name of an existing EC2' + \
    'KeyPair to enable SSH access to the instances",' + \
    '''
          "Type" : "String",
          "Label" : "Nova KeyPair Name"
        },
  },

  "Resources" : {
     "AName": {
          "Type": "AWS::EC2::Instance",
          "Properties": {
            "ImageId": "image_name",
            "InstanceType": "m1.large",
            "KeyName": { "Ref" : "KeyName" },
            "NetworkInterfaces": [ "mgmt", "data" ]
          }
     }
  }
}
'''

test_template_hot_parameter_label = '''
heat_template_version: 2013-05-23

description: >
  Hello world HOT template that just defines a single compute instance.
  Contains just base features to verify base HOT support.

parameters:
  KeyName:
    type: string
    description: Name of an existing key pair to use for the instance
    label: Nova KeyPair Name

resources:
  my_instance:
    type: AWS::EC2::Instance
    properties:
      KeyName: { get_param: KeyName }
      ImageId: { get_param: ImageId }
      InstanceType: { get_param: InstanceType }

outputs:
  instance_ip:
    description: The IP address of the deployed instance
    value: { get_attr: [my_instance, PublicIp] }
'''

test_template_duplicate_parameters = '''
# This is a hello world HOT template just defining a single compute instance
heat_template_version: 2013-05-23

parameter_groups:
  - label: Server Group
    description: A group of parameters for the server
    parameters:
    - InstanceType
    - KeyName
    - ImageId
  - label: Database Group
    description: A group of parameters for the database
    parameters:
    - db_password
    - db_port
    - InstanceType

parameters:
  KeyName:
    type: string
    description: Name of an existing key pair to use for the instance
  InstanceType:
    type: string
    description: Instance type for the instance to be created
    default: m1.small
    constraints:
      - allowed_values: [m1.tiny, m1.small, m1.large]
        description: Value must be one of 'm1.tiny', 'm1.small' or 'm1.large'
  ImageId:
    type: string
    description: ID of the image to use for the instance
  # parameters below are not used in template, but are for verifying parameter
  # validation support in HOT
  db_password:
    type: string
    description: Database password
    hidden: true
    constraints:
      - length: { min: 6, max: 8 }
        description: Password length must be between 6 and 8 characters
      - allowed_pattern: "[a-zA-Z0-9]+"
        description: Password must consist of characters and numbers only
      - allowed_pattern: "[A-Z]+[a-zA-Z0-9]*"
        description: Password must start with an uppercase character
  db_port:
    type: number
    description: Database port number
    default: 50000
    constraints:
      - range: { min: 40000, max: 60000 }
        description: Port number must be between 40000 and 60000

resources:
  my_instance:
    # Use an AWS resource type since this exists; so why use other name here?
    type: AWS::EC2::Instance
    properties:
      KeyName: { get_param: KeyName }
      ImageId: { get_param: ImageId }
      InstanceType: { get_param: InstanceType }

outputs:
  instance_ip:
    description: The IP address of the deployed instance
    value: { get_attr: [my_instance, PublicIp] }
'''

test_template_invalid_parameter_name = '''
# This is a hello world HOT template just defining a single compute instance
heat_template_version: 2013-05-23

description: >
  Hello world HOT template that just defines a single compute instance.
  Contains just base features to verify base HOT support.

parameter_groups:
  - label: Server Group
    description: A group of parameters for the server
    parameters:
    - InstanceType
    - KeyName
    - ImageId
  - label: Database Group
    description: A group of parameters for the database
    parameters:
    - db_password
    - db_port
    - SomethingNotHere

parameters:
  KeyName:
    type: string
    description: Name of an existing key pair to use for the instance
  InstanceType:
    type: string
    description: Instance type for the instance to be created
    default: m1.small
    constraints:
      - allowed_values: [m1.tiny, m1.small, m1.large]
        description: Value must be one of 'm1.tiny', 'm1.small' or 'm1.large'
  ImageId:
    type: string
    description: ID of the image to use for the instance
  # parameters below are not used in template, but are for verifying parameter
  # validation support in HOT
  db_password:
    type: string
    description: Database password
    hidden: true
    constraints:
      - length: { min: 6, max: 8 }
        description: Password length must be between 6 and 8 characters
      - allowed_pattern: "[a-zA-Z0-9]+"
        description: Password must consist of characters and numbers only
      - allowed_pattern: "[A-Z]+[a-zA-Z0-9]*"
        description: Password must start with an uppercase character
  db_port:
    type: number
    description: Database port number
    default: 50000
    constraints:
      - range: { min: 40000, max: 60000 }
        description: Port number must be between 40000 and 60000

resources:
  my_instance:
    # Use an AWS resource type since this exists; so why use other name here?
    type: AWS::EC2::Instance
    properties:
      KeyName: { get_param: KeyName }
      ImageId: { get_param: ImageId }
      InstanceType: { get_param: InstanceType }

outputs:
  instance_ip:
    description: The IP address of the deployed instance
    value: { get_attr: [my_instance, PublicIp] }
'''

test_template_hot_no_parameter_label = '''
heat_template_version: 2013-05-23

description: >
  Hello world HOT template that just defines a single compute instance.
  Contains just base features to verify base HOT support.

parameters:
  KeyName:
    type: string
    description: Name of an existing key pair to use for the instance

resources:
  my_instance:
    type: AWS::EC2::Instance
    properties:
      KeyName: { get_param: KeyName }
      ImageId: { get_param: ImageId }
      InstanceType: { get_param: InstanceType }
'''

test_template_no_parameters = '''
heat_template_version: 2013-05-23

description: >
  Hello world HOT template that just defines a single compute instance.
  Contains just base features to verify base HOT support.

parameter_groups:
  - label: Server Group
    description: A group of parameters for the server
  - label: Database Group
    description: A group of parameters for the database

resources:
  server:
    type: OS::Nova::Server
'''

test_template_allowed_integers = '''
heat_template_version: 2013-05-23

parameters:
  size:
    type: number
    constraints:
      - allowed_values: [1, 4, 8]
resources:
  my_volume:
    type: OS::Cinder::Volume
    properties:
      size: { get_param: size }
'''

test_template_allowed_integers_str = '''
heat_template_version: 2013-05-23

parameters:
  size:
    type: number
    constraints:
      - allowed_values: ['1', '4', '8']
resources:
  my_volume:
    type: OS::Cinder::Volume
    properties:
      size: { get_param: size }
'''

test_template_default_override = '''
heat_template_version: 2013-05-23

description:  create a network

parameters:
  net_name:
    type: string
    default: defaultnet
    description: Name of private network to be created

resources:
  private_net:
    type: OS::Neutron::Net
    properties:
      name: { get_param: net_name }
'''

test_template_no_default = '''
heat_template_version: 2013-05-23

description:  create a network

parameters:
  net_name:
    type: string
    description: Name of private network to be created

resources:
  private_net:
    type: OS::Neutron::Net
    properties:
      name: { get_param: net_name }
'''


class validateTest(HeatTestCase):
    def setUp(self):
        super(validateTest, self).setUp()
        resources.initialise()
        self.fc = fakes.FakeClient()
        self.gc = fakes.FakeClient()
        resources.initialise()
        self.ctx = utils.dummy_context()
        self.patch('heat.engine.service.warnings')

    def _mock_get_image_id_success(self, imageId_input, imageId):
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(
            imageId_input).MultipleTimes().AndReturn(imageId)

    def _mock_get_image_id_fail(self, image_id, exp):
        self.m.StubOutWithMock(glance.GlanceClientPlugin, 'get_image_id')
        glance.GlanceClientPlugin.get_image_id(image_id).AndRaise(exp)

    def test_validate_volumeattach_valid(self):
        t = template_format.parse(test_template_volumeattach % 'vdq')
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template(t))

        volumeattach = stack['MountPoint']
        self.assertIsNone(volumeattach.validate())

    def test_validate_volumeattach_invalid(self):
        t = template_format.parse(test_template_volumeattach % 'sda')
        stack = parser.Stack(self.ctx, 'test_stack', parser.Template(t))

        volumeattach = stack['MountPoint']
        self.assertRaises(exception.StackValidationFailed,
                          volumeattach.validate)

    def test_validate_ref_valid(self):
        t = template_format.parse(test_template_ref % 'WikiDatabase')
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual('test.', res['Description'])

    def test_validate_with_environment(self):
        test_template = test_template_ref % 'WikiDatabase'
        test_template = test_template.replace('AWS::EC2::Instance',
                                              'My::Instance')
        t = template_format.parse(test_template)
        engine = service.EngineService('a', 't')
        params = {'resource_registry': {'My::Instance': 'AWS::EC2::Instance'}}
        res = dict(engine.validate_template(None, t, params))
        self.assertEqual('test.', res['Description'])

    def test_validate_hot_valid(self):
        t = template_format.parse(
            """
            heat_template_version: 2013-05-23
            description: test.
            resources:
              my_instance:
                type: AWS::EC2::Instance
            """)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual('test.', res['Description'])

    def test_validate_ref_invalid(self):
        t = template_format.parse(test_template_ref % 'WikiDatabasez')
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertNotEqual(res['Description'], 'Successfully validated')

    def test_validate_findinmap_valid(self):
        t = template_format.parse(test_template_findinmap_valid)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual('test.', res['Description'])

    def test_validate_findinmap_invalid(self):
        t = template_format.parse(test_template_findinmap_invalid)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertNotEqual(res['Description'], 'Successfully validated')

    def test_validate_parameters(self):
        t = template_format.parse(test_template_ref % 'WikiDatabase')
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        # Note: the assertion below does not expect a CFN dict of the parameter
        # but a dict of the parameters.Schema object.
        # For API CFN backward compatibility, formating to CFN is done in the
        # API layer in heat.engine.api.format_validate_parameter.
        expected = {'KeyName': {
            'Type': 'String',
            'Description': 'Name of an existing EC2KeyPair to enable SSH '
                           'access to the instances',
            'NoEcho': 'false',
            'Label': 'KeyName'}}
        self.assertEqual(expected, res['Parameters'])

    def test_validate_parameters_env_override(self):
        t = template_format.parse(test_template_default_override)
        env_params = {'net_name': 'betternetname'}
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, env_params))
        self.assertEqual('betternetname',
                         res['Parameters']['net_name']['Default'])

    def test_validate_parameters_env_provided(self):
        t = template_format.parse(test_template_no_default)
        env_params = {'net_name': 'betternetname'}
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, env_params))
        self.assertEqual('betternetname',
                         res['Parameters']['net_name']['Default'])

    def test_validate_hot_empty_parameters_valid(self):
        t = template_format.parse(
            """
            heat_template_version: 2013-05-23
            description: test.
            parameters:
            resources:
              my_instance:
                type: AWS::EC2::Instance
            """)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual({}, res['Parameters'])

    def test_validate_hot_parameter_label(self):
        t = template_format.parse(test_template_hot_parameter_label)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        parameters = res['Parameters']

        expected = {'KeyName': {
            'Type': 'String',
            'Description': 'Name of an existing key pair to use for the '
                           'instance',
            'NoEcho': 'false',
            'Label': 'Nova KeyPair Name'}}
        self.assertEqual(expected, parameters)

    def test_validate_hot_no_parameter_label(self):
        t = template_format.parse(test_template_hot_no_parameter_label)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        parameters = res['Parameters']

        expected = {'KeyName': {
            'Type': 'String',
            'Description': 'Name of an existing key pair to use for the '
                           'instance',
            'NoEcho': 'false',
            'Label': 'KeyName'}}
        self.assertEqual(expected, parameters)

    def test_validate_cfn_parameter_label(self):
        t = template_format.parse(test_template_cfn_parameter_label)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        parameters = res['Parameters']

        expected = {'KeyName': {
            'Type': 'String',
            'Description': 'Name of an existing EC2KeyPair to enable SSH '
                           'access to the instances',
            'NoEcho': 'false',
            'Label': 'Nova KeyPair Name'}}
        self.assertEqual(expected, parameters)

    def test_validate_hot_parameter_type(self):
        t = template_format.parse(
            """
            heat_template_version: 2013-05-23
            parameters:
              param1:
                type: string
              param2:
                type: number
              param3:
                type: json
              param4:
                type: comma_delimited_list
              param5:
                type: boolean
            """)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        parameters = res['Parameters']
        # make sure all the types are reported correctly
        self.assertEqual('String', parameters["param1"]["Type"])
        self.assertEqual('Number', parameters["param2"]["Type"])
        self.assertEqual('Json', parameters["param3"]["Type"])
        self.assertEqual('CommaDelimitedList', parameters["param4"]["Type"])
        self.assertEqual('Boolean', parameters["param5"]["Type"])

    def test_validate_hot_empty_resources_valid(self):
        t = template_format.parse(
            """
            heat_template_version: 2013-05-23
            description: test.
            resources:
            """)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        expected = {"Description": "test.",
                    "Parameters": {}}
        self.assertEqual(expected, res)

    def test_validate_hot_empty_outputs_valid(self):
        t = template_format.parse(
            """
            heat_template_version: 2013-05-23
            description: test.
            outputs:
            """)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        expected = {"Description": "test.",
                    "Parameters": {}}
        self.assertEqual(expected, res)

    def test_validate_properties(self):
        t = template_format.parse(test_template_invalid_property)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual({'Error': 'Unknown Property UnknownProperty'}, res)

    def test_invalid_resources(self):
        t = template_format.parse(test_template_invalid_resources)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual({'Error': 'Resources must contain Resource. '
                          'Found a [string] instead'},
                         res)

    def test_invalid_section_cfn(self):
        t = template_format.parse(
            """
            {
                'AWSTemplateFormatVersion': '2010-09-09',
                'Resources': {
                    'server': {
                        'Type': 'OS::Nova::Server'
                    }
                },
                'Output': {}
            }
            """)

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual({'Error': 'The template section is invalid: Output'},
                         res)

    def test_invalid_section_hot(self):
        t = template_format.parse(
            """
            heat_template_version: 2013-05-23
            resources:
              server:
                type: OS::Nova::Server
            output:
            """)

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t))
        self.assertEqual({'Error': 'The template section is invalid: output'},
                         res)

    def test_unimplemented_property(self):
        t = template_format.parse(test_template_unimplemented_property)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual(
            {'Error': 'Property SourceDestCheck not implemented yet'},
            res)

    def test_invalid_deletion_policy(self):
        t = template_format.parse(test_template_invalid_deletion_policy)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual({'Error': 'Invalid deletion policy "Destroy"'}, res)

    def test_snapshot_deletion_policy(self):
        t = template_format.parse(test_template_snapshot_deletion_policy)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual(
            {'Error': '"Snapshot" deletion policy not supported'}, res)

    def test_volume_snapshot_deletion_policy(self):
        t = template_format.parse(test_template_volume_snapshot)
        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, t, {}))
        self.assertEqual({'Description': u'test.', 'Parameters': {}}, res)

    def test_validate_template_without_resources(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        ''')

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, hot_tpl, {}))
        expected = {'Description': 'No description', 'Parameters': {}}
        self.assertEqual(expected, res)

    def test_validate_template_with_invalid_resource_type(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            Type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, hot_tpl, {}))
        self.assertEqual({'Error': 'u\'"Type" is not a valid keyword '
                                   'inside a resource definition\''}, res)

    def test_validate_template_with_invalid_resource_properties(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            Properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, hot_tpl, {}))
        self.assertEqual({'Error': 'u\'"Properties" is not a valid keyword '
                                   'inside a resource definition\''}, res)

    def test_validate_template_with_invalid_resource_matadata(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            Metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, hot_tpl, {}))
        self.assertEqual({'Error': 'u\'"Metadata" is not a valid keyword '
                                   'inside a resource definition\''}, res)

    def test_validate_template_with_invalid_resource_depends_on(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            DependsOn: dummy
            deletion_policy: dummy
            update_policy:
              foo: bar
        ''')

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, hot_tpl, {}))
        self.assertEqual({'Error': 'u\'"DependsOn" is not a valid keyword '
                                   'inside a resource definition\''}, res)

    def test_validate_template_with_invalid_resource_deletion_polciy(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            DeletionPolicy: dummy
            update_policy:
              foo: bar
        ''')

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, hot_tpl, {}))
        self.assertEqual({'Error': 'u\'"DeletionPolicy" is not a valid '
                                   'keyword inside a resource definition\''},
                         res)

    def test_validate_template_with_invalid_resource_update_policy(self):
        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
            metadata:
              foo: bar
            depends_on: dummy
            deletion_policy: dummy
            UpdatePolicy:
              foo: bar
        ''')

        engine = service.EngineService('a', 't')
        res = dict(engine.validate_template(None, hot_tpl, {}))
        self.assertEqual({'Error': 'u\'"UpdatePolicy" is not a valid '
                                   'keyword inside a resource definition\''},
                         res)

    def test_unregistered_key(self):
        t = template_format.parse(test_unregistered_key)
        template = parser.Template(t)
        params = {'KeyName': 'not_registered'}
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment(params))

        self._mock_get_image_id_success('image_name', 'image_id')
        self.m.ReplayAll()

        resource = stack['Instance']
        self.assertRaises(exception.StackValidationFailed, resource.validate)
        self.m.VerifyAll()

    def test_unregistered_image(self):
        t = template_format.parse(test_template_image)
        template = parser.Template(t)

        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'KeyName': 'test'}))

        self._mock_get_image_id_fail('image_name',
                                     exception.ImageNotFound(
                                         image_name='image_name'))
        self.m.ReplayAll()

        resource = stack['Instance']
        self.assertRaises(exception.StackValidationFailed, resource.validate)

        self.m.VerifyAll()

    def test_duplicated_image(self):
        t = template_format.parse(test_template_image)
        template = parser.Template(t)

        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'KeyName': 'test'}))

        self._mock_get_image_id_fail('image_name',
                                     exception.PhysicalResourceNameAmbiguity(
                                         name='image_name'))

        self.m.ReplayAll()

        resource = stack['Instance']
        self.assertRaises(exception.StackValidationFailed,
                          resource.validate)

        self.m.VerifyAll()

    def test_invalid_security_groups_with_nics(self):
        t = template_format.parse(test_template_invalid_secgroups)
        template = parser.Template(t)
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'KeyName': 'test'}))

        self._mock_get_image_id_success('image_name', 'image_id')

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.m.ReplayAll()

        resource = stack['Instance']
        self.assertRaises(exception.ResourcePropertyConflict,
                          resource.validate)
        self.m.VerifyAll()

    def test_invalid_security_group_ids_with_nics(self):
        t = template_format.parse(test_template_invalid_secgroupids)
        template = parser.Template(t)
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'KeyName': 'test'}))

        self._mock_get_image_id_success('image_name', 'image_id')

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self.m.ReplayAll()

        resource = stack['Instance']
        self.assertRaises(exception.ResourcePropertyConflict,
                          resource.validate)
        self.m.VerifyAll()

    def test_client_exception_from_glance_client(self):
        t = template_format.parse(test_template_glance_client_exception)
        template = parser.Template(t)
        stack = parser.Stack(self.ctx, 'test_stack', template)

        self.m.StubOutWithMock(self.gc.images, 'list')
        self.gc.images.list().AndRaise(
            glance_exceptions.ClientException(500))
        self.m.StubOutWithMock(glance.GlanceClientPlugin, '_create')
        glance.GlanceClientPlugin._create().AndReturn(self.gc)
        self.m.ReplayAll()

        self.assertRaises(exception.StackValidationFailed, stack.validate)
        self.m.VerifyAll()

    def test_validate_unique_logical_name(self):
        t = template_format.parse(test_template_unique_logical_name)
        template = parser.Template(t)
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'AName': 'test',
                                                      'KeyName': 'test'}))

        self.assertRaises(exception.StackValidationFailed, stack.validate)

    def test_validate_duplicate_parameters_in_group(self):
        t = template_format.parse(test_template_duplicate_parameters)
        template = HOTemplate20130523(t)
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({
                                 'KeyName': 'test',
                                 'ImageId': 'sometestid',
                                 'db_password': 'Pass123'
                             }))
        exc = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)

        self.assertEqual(_('The InstanceType parameter must be assigned to '
                         'one Parameter Group only.'), six.text_type(exc))

    def test_validate_invalid_parameter_in_group(self):
        t = template_format.parse(test_template_invalid_parameter_name)
        template = HOTemplate20130523(t)
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({
                                 'KeyName': 'test',
                                 'ImageId': 'sometestid',
                                 'db_password': 'Pass123'}))

        exc = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)

        self.assertEqual(_('The Parameter name (SomethingNotHere) does not '
                         'reference an existing parameter.'),
                         six.text_type(exc))

    def test_validate_no_parameters_in_group(self):
        t = template_format.parse(test_template_no_parameters)
        template = HOTemplate20130523(t)
        stack = parser.Stack(self.ctx, 'test_stack', template)
        exc = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)

        self.assertEqual(_('Parameters must be provided for each Parameter '
                         'Group.'), six.text_type(exc))

    def test_validate_allowed_values_integer(self):
        t = template_format.parse(test_template_allowed_integers)
        template = parser.Template(t)

        # test with size parameter provided as string
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': '4'}))
        self.assertIsNone(stack.validate())

        # test with size parameter provided as number
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': 4}))
        self.assertIsNone(stack.validate())

    def test_validate_allowed_values_integer_str(self):
        t = template_format.parse(test_template_allowed_integers_str)
        template = parser.Template(t)

        # test with size parameter provided as string
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': '4'}))
        self.assertIsNone(stack.validate())

        # test with size parameter provided as number
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': 4}))
        self.assertIsNone(stack.validate())

    def test_validate_not_allowed_values_integer(self):
        t = template_format.parse(test_template_allowed_integers)
        template = parser.Template(t)

        # test with size parameter provided as string
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': '3'}))
        err = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('"3" is not an allowed value [1, 4, 8]',
                      six.text_type(err))

        # test with size parameter provided as number
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': 3}))
        err = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('"3" is not an allowed value [1, 4, 8]',
                      six.text_type(err))

    def test_validate_not_allowed_values_integer_str(self):
        t = template_format.parse(test_template_allowed_integers_str)
        template = parser.Template(t)

        # test with size parameter provided as string
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': '3'}))
        err = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('"3" is not an allowed value [1, 4, 8]',
                      six.text_type(err))

        # test with size parameter provided as number
        stack = parser.Stack(self.ctx, 'test_stack', template,
                             environment.Environment({'size': 3}))
        err = self.assertRaises(exception.StackValidationFailed,
                                stack.validate)
        self.assertIn('"3" is not an allowed value [1, 4, 8]',
                      six.text_type(err))
