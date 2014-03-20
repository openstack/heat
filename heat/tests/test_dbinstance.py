
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
from heat.engine import parser
from heat.engine import resource
from heat.tests.common import HeatTestCase
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
    """This is copied from the old DBInstance
    to verify the schema of the new TemplateResource.
    """
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

    # We only support a couple of the attributes right now
    attributes_schema = {
        "Endpoint.Address": "Connection endpoint for the database.",
        "Endpoint.Port": ("The port number on which the database accepts "
                          "connections.")
    }


class DBInstanceTest(HeatTestCase):
    def setUp(self):
        super(DBInstanceTest, self).setUp()
        utils.setup_dummy_db()

    def test_dbinstance(self):
        """test that the Template is parsable and
        publishes the correct properties.
        """
        templ = parser.Template(template_format.parse(rds_template))
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             templ)

        res = stack['DatabaseServer']
        self.assertIsNone(res._validate_against_facade(DBInstance))
