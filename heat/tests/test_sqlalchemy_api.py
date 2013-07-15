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

from heat.db.sqlalchemy import api as db_api
from heat.engine import environment
from heat.tests.v1_1 import fakes
from heat.engine.resource import Resource
from heat.common import template_format
from heat.engine import parser
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db


wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "wordpress"
      }
    }
  }
}
'''


class MyResource(Resource):
    properties_schema = {
        'ServerName': {'Type': 'String', 'Required': True},
        'Flavor': {'Type': 'String', 'Required': True},
        'ImageName': {'Type': 'String', 'Required': True},
        'UserData': {'Type': 'String'},
        'PublicKey': {'Type': 'String'}
    }

    @property
    def my_secret(self):
        return db_api.resource_data_get(self, 'my_secret')

    @my_secret.setter
    def my_secret(self, my_secret):
        db_api.resource_data_set(self, 'my_secret', my_secret, True)


class SqlAlchemyTest(HeatTestCase):
    def setUp(self):
        super(SqlAlchemyTest, self).setUp()
        self.fc = fakes.FakeClient()
        setup_dummy_db()

    def _setup_test_stack(self, stack_name):
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack = parser.Stack(None, stack_name, template,
                             environment.Environment({'KeyName': 'test'}),
                             stack_id=uuidutils.generate_uuid())
        return (t, stack)

    def test_encryption(self):
        stack_name = 'test_encryption'
        (t, stack) = self._setup_test_stack(stack_name)
        cs = MyResource('cs_encryption',
                        t['Resources']['WebServer'],
                        stack)

        # This gives the fake cloud server an id and created_time attribute
        cs._store_or_update(cs.CREATE, cs.IN_PROGRESS, 'test_store')

        cs.my_secret = 'fake secret'
        rs = db_api.resource_get_by_name_and_stack(None,
                                                   'cs_encryption',
                                                   stack.id)
        encrypted_key = rs.data[0]['value']
        self.assertNotEqual(encrypted_key, "fake secret")
        decrypted_key = cs.my_secret
        self.assertEqual(decrypted_key, "fake secret")
