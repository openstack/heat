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

from heat.common import template_format
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils


rds_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "RDS Test",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
   },
  "Resources" : {
    "DatabaseServer": {
      "Type": "AWS::RDS::DBInstance",
      "Properties": {
        "DBName"            : "wordpress",
        "Engine"            : "MySQL",
        "MasterUsername"    : "admin",
        "DBInstanceClass"   : "db.m1.small",
        "DBSecurityGroups"  : [],
        "AllocatedStorage"  : "5",
        "MasterUserPassword": "admin"
      }
    }
  }
}
'''


class DBInstance(resource.Resource):
    """Verify the schema of the new TemplateResource.

    This is copied from the old DBInstance.
    """
    properties_schema = {
        'DBSnapshotIdentifier': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'AllocatedStorage': properties.Schema(
            properties.Schema.STRING,
            required=True
        ),
        'AvailabilityZone': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'BackupRetentionPeriod': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'DBInstanceClass': properties.Schema(
            properties.Schema.STRING,
            required=True
        ),
        'DBName': properties.Schema(
            properties.Schema.STRING,
            required=False
        ),
        'DBParameterGroupName': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'DBSecurityGroups': properties.Schema(
            properties.Schema.LIST,
            required=False,
            default=[]
        ),
        'DBSubnetGroupName': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'Engine': properties.Schema(
            properties.Schema.STRING,
            constraints=[
                constraints.AllowedValues(['MySQL']),
            ],
            required=True
        ),
        'EngineVersion': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'LicenseModel': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'MasterUsername': properties.Schema(
            properties.Schema.STRING,
            required=True
        ),
        'MasterUserPassword': properties.Schema(
            properties.Schema.STRING,
            required=True
        ),
        'Port': properties.Schema(
            properties.Schema.STRING,
            required=False,
            default='3306'
        ),
        'PreferredBackupWindow': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'PreferredMaintenanceWindow': properties.Schema(
            properties.Schema.STRING,
            implemented=False
        ),
        'MultiAZ': properties.Schema(
            properties.Schema.BOOLEAN,
            implemented=False
        ),
    }

    # We only support a couple of the attributes right now
    attributes_schema = {
        "Endpoint.Address": attributes.Schema(
            "Connection endpoint for the database."
        ),
        "Endpoint.Port": attributes.Schema(
            ("The port number on which the database accepts "
             "connections.")
        ),
    }


class DBInstanceTest(common.HeatTestCase):
    def test_dbinstance(self):
        """Test that Template is parsable and publishes correct properties."""
        templ = template.Template(template_format.parse(rds_template))
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             templ)

        res = stack['DatabaseServer']
        self.assertIsNone(res._validate_against_facade(DBInstance))
