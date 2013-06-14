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

from heat.common import exception
from heat.common import template_format
from heat.engine import scheduler
from heat.engine.resources import dbinstance as dbi
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack


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


class DBInstanceTest(HeatTestCase):
    def setUp(self):
        super(DBInstanceTest, self).setUp()
        setup_dummy_db()
        self.m.StubOutWithMock(dbi.DBInstance, 'create_with_template')
        self.m.StubOutWithMock(dbi.DBInstance, 'check_create_complete')
        self.m.StubOutWithMock(dbi.DBInstance, 'nested')

    def create_dbinstance(self, t, stack, resource_name):
        resource = dbi.DBInstance(resource_name,
                                  t['Resources'][resource_name],
                                  stack)
        self.assertEqual(None, resource.validate())
        scheduler.TaskRunner(resource.create)()
        self.assertEqual((resource.CREATE, resource.COMPLETE), resource.state)
        return resource

    def test_dbinstance(self):

        class FakeDatabaseInstance:
            def _ipaddress(self):
                return '10.0.0.1'

        class FakeNested:
            resources = {'DatabaseInstance': FakeDatabaseInstance()}

        params = {'DBSecurityGroups': '',
                  'MasterUsername': u'admin',
                  'MasterUserPassword': u'admin',
                  'DBName': u'wordpress',
                  'KeyName': u'test',
                  'AllocatedStorage': u'5',
                  'DBInstanceClass': u'db.m1.small',
                  'Port': '3306'}

        dbi.DBInstance.create_with_template(mox.IgnoreArg(),
                                            params).AndReturn(None)
        dbi.DBInstance.check_create_complete(mox.IgnoreArg()).AndReturn(True)

        fn = FakeNested()

        dbi.DBInstance.nested().AndReturn(None)
        dbi.DBInstance.nested().MultipleTimes().AndReturn(fn)
        self.m.ReplayAll()

        t = template_format.parse(rds_template)
        s = parse_stack(t)
        resource = self.create_dbinstance(t, s, 'DatabaseServer')

        self.assertEqual('0.0.0.0', resource.FnGetAtt('Endpoint.Address'))
        self.assertEqual('10.0.0.1', resource.FnGetAtt('Endpoint.Address'))
        self.assertEqual('3306', resource.FnGetAtt('Endpoint.Port'))

        try:
            resource.FnGetAtt('foo')
        except exception.InvalidTemplateAttribute:
            pass
        else:
            raise Exception('Expected InvalidTemplateAttribute')

        self.m.VerifyAll()
