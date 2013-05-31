# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.common import exception
from heat.engine import stack_resource
from heat.common import template_format
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)

mysql_template = r'''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "Builtin RDS::DBInstance",
  "Parameters" : {
    "DBInstanceClass" : {
      "Type": "String"
    },

    "DBName" : {
      "Type": "String"
    },

    "MasterUsername" : {
      "Type": "String"
    },

    "MasterUserPassword" : {
      "Type": "String"
    },

    "AllocatedStorage" : {
      "Type": "String"
    },

    "DBSecurityGroups" : {
      "Type": "CommaDelimitedList",
      "Default": ""
    },

    "Port" : {
      "Type": "String"
    },

    "KeyName" : {
      "Type" : "String"
    }
  },

  "Mappings" : {
    "DBInstanceToInstance" : {
      "db.m1.small": {"Instance": "m1.small"},
      "db.m1.large": {"Instance": "m1.large"},
      "db.m1.xlarge": {"Instance": "m1.xlarge"},
      "db.m2.xlarge": {"Instance": "m2.xlarge"},
      "db.m2.2xlarge": {"Instance": "m2.2xlarge"},
      "db.m2.4xlarge": {"Instance": "m2.4xlarge"}
    }
  },


  "Resources": {
    "DatabaseInstance": {
      "Type": "AWS::EC2::Instance",
      "Metadata": {
        "AWS::CloudFormation::Init": {
          "config": {
            "packages": {
              "yum": {
                "mysql"        : [],
                "mysql-server" : []
              }
            },
            "services": {
              "systemd": {
                "mysqld"   : { "enabled" : "true", "ensureRunning" : "true" }
              }
            }
          }
        }
      },
      "Properties": {
        "ImageId": "F17-x86_64-cfntools",
        "InstanceType": { "Fn::FindInMap": [ "DBInstanceToInstance",
                                             { "Ref": "DBInstanceClass" },
                                             "Instance" ] },
        "KeyName": { "Ref": "KeyName" },
        "UserData": { "Fn::Base64": { "Fn::Join": ["", [
          "#!/bin/bash -v\n",
          "# Helper function\n",
          "function error_exit\n",
          "{\n",
          "  /opt/aws/bin/cfn-signal -e 1 -r \"$1\" '",
          { "Ref" : "WaitHandle" }, "'\n",
          "  exit 1\n",
          "}\n",

          "/opt/aws/bin/cfn-init -s ", { "Ref" : "AWS::StackName" },
          " -r DatabaseInstance",
          " --region ", { "Ref" : "AWS::Region" },
          " || error_exit 'Failed to run cfn-init'\n",
          "# Setup MySQL root password and create a user\n",
          "mysqladmin -u root password '", {"Ref":"MasterUserPassword"},"'\n",
          "cat << EOF | mysql -u root --password='",
                                      { "Ref" : "MasterUserPassword" }, "'\n",
          "CREATE DATABASE ", { "Ref" : "DBName" }, ";\n",
          "GRANT ALL PRIVILEGES ON ", { "Ref" : "DBName" },
                    ".* TO \"", { "Ref" : "MasterUsername" }, "\"@\"%\"\n",
          "IDENTIFIED BY \"", { "Ref" : "MasterUserPassword" }, "\";\n",
          "FLUSH PRIVILEGES;\n",
          "EXIT\n",
          "EOF\n",
          "# Database setup completed, signal success\n",
          "/opt/aws/bin/cfn-signal -e 0 -r \"MySQL server setup complete\" '",
          { "Ref" : "WaitHandle" }, "'\n"

        ]]}}
      }
    },

    "WaitHandle" : {
      "Type" : "AWS::CloudFormation::WaitConditionHandle"
    },

    "WaitCondition" : {
      "Type" : "AWS::CloudFormation::WaitCondition",
      "DependsOn" : "DatabaseInstance",
      "Properties" : {
        "Handle" : {"Ref" : "WaitHandle"},
        "Timeout" : "600"
      }
    }
  },

  "Outputs": {
  }
}
'''


class DBInstance(stack_resource.StackResource):

    properties_schema = {
        'DBSnapshotIdentifier': {'Type': 'String',
                                 'Implemented': False},
        'AllocatedStorage': {'Type': 'String',
                             'Required': True},
        'AvailabilityZone': {'Type': 'String',
                             'Implemented': False},
        'BackupRetentionPeriod': {'Type': 'String',
                                  'Implemented': False},
        'DBInstanceClass': {'Type': 'String',
                            'Required': True},
        'DBName': {'Type': 'String',
                   'Required': False},
        'DBParameterGroupName': {'Type': 'String',
                                 'Implemented': False},
        'DBSecurityGroups': {'Type': 'List',
                             'Required': False, 'Default': []},
        'DBSubnetGroupName': {'Type': 'String',
                              'Implemented': False},
        'Engine': {'Type': 'String',
                   'AllowedValues': ['MySQL'],
                   'Required': True},
        'EngineVersion': {'Type': 'String',
                          'Implemented': False},
        'LicenseModel': {'Type': 'String',
                         'Implemented': False},
        'MasterUsername': {'Type': 'String',
                           'Required': True},
        'MasterUserPassword': {'Type': 'String',
                               'Required': True},
        'Port': {'Type': 'String',
                 'Default': '3306',
                 'Required': False},
        'PreferredBackupWindow': {'Type': 'String',
                                  'Implemented': False},
        'PreferredMaintenanceWindow': {'Type': 'String',
                                       'Implemented': False},
        'MultiAZ': {'Type': 'Boolean',
                    'Implemented': False},
    }

    def _params(self):
        params = {
            'KeyName': {'Ref': 'KeyName'},
        }

        # Add the DBInstance parameters specified in the user's template
        # Ignore the not implemented ones
        for key, value in self.properties_schema.items():
            if value.get('Implemented', True) and key != 'Engine':
                # There is a mismatch between the properties "List" format
                # and the parameters "CommaDelimitedList" format, so we need
                # to translate lists into the expected comma-delimited form
                if isinstance(self.properties[key], list):
                    params[key] = ','.join(self.properties[key])
                else:
                    params[key] = self.properties[key]
        p = self.stack.resolve_static_data(params)
        return p

    def handle_create(self):
        templ = template_format.parse(mysql_template)
        return self.create_with_template(templ, self._params())

    def handle_delete(self):
        self.delete_nested()

    def FnGetAtt(self, key):
        '''
        We don't really support any of these yet.
        '''
        if key == 'Endpoint.Address':
            if self.nested() and 'DatabaseInstance' in self.nested().resources:
                return self.nested().resources['DatabaseInstance']._ipaddress()
            else:
                return '0.0.0.0'
        elif key == 'Endpoint.Port':
            return self.properties['Port']
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


def resource_mapping():
    return {
        'AWS::RDS::DBInstance': DBInstance,
    }
