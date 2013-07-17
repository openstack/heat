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


from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine import environment
from heat.engine import resource
from heat.engine.resources.rackspace import clouddatabase
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests.utils import setup_dummy_db


wp_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "MYSQL instance running on Rackspace cloud",
  "Parameters" : {
    "FlavorRef": {
      "Description" : "Flavor reference",
      "Type": "String"
    },
    "VolumeSize": {
      "Description" : "The volume size",
      "Type": "Number",
      "MinValue" : "1",
      "MaxValue" : "1024"
    },
    "InstanceName": {
      "Description" : "The database instance name",
      "Type": "String"
    }
  },
  "Resources" : {
    "MySqlCloudDB": {
      "Type": "Rackspace::Cloud::DBInstance",
      "Properties" : {
        "InstanceName" : {"Ref": "InstanceName"},
        "FlavorRef" : {"Ref": "FlavorRef"},
        "VolumeSize" : {"Ref": VolumeSize},
        "Users" : [{"name":"testuser", "password":"testpass123"}] ,
        "Databases" : [{"name":"testdbonetwo"}]
      }
    }
  }

}
'''


class FakeDBInstance(object):
    def __init__(self):
        self.id = 12345
        self.hostname = "testhost"
        self.links = \
            [{"href": "https://adga23dd432a.rackspacecloud.com/132345245"}]
        self.resource_id = 12345


class CloudDBInstanceTest(HeatTestCase):
    def setUp(self):
        super(CloudDBInstanceTest, self).setUp()
        setup_dummy_db()
        # Test environment may not have pyrax client library installed and if
        # pyrax is not installed resource class would not be registered.
        # So register resource provider class explicitly for unit testing.
        resource._register_class("Rackspace::Cloud::DBInstance",
                                 clouddatabase.CloudDBInstance)

    def _setup_test_clouddbinstance(self, name, inject_property_error=False):
        stack_name = '%s_stack' % name
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack = parser.Stack(None,
                             stack_name,
                             template,
                             environment.Environment({'InstanceName': 'Test',
                                                      'FlavorRef': '1GB',
                                                      'VolumeSize': '30'}),
                             stack_id=uuidutils.generate_uuid())

        if inject_property_error:
            # database name given in users list is not a valid database
            t['Resources']['MySqlCloudDB']['Properties']['Databases'] = \
                [{"Name": "onedb"}]
            t['Resources']['MySqlCloudDB']['Properties']['Users'] = \
                [{"Name": "testuser",
                  "Password": "pass",
                  "Databases": ["invaliddb"]}]
        else:
            t['Resources']['MySqlCloudDB']['Properties']['Databases'] = \
                [{"Name": "validdb"}]
            t['Resources']['MySqlCloudDB']['Properties']['Users'] = \
                [{"Name": "testuser",
                  "Password": "pass",
                  "Databases": ["validdb"]}]

        instance = clouddatabase.CloudDBInstance(
            '%s_name' % name,
            t['Resources']['MySqlCloudDB'],
            stack)
        instance.resource_id = 1234
        self.m.StubOutWithMock(instance, 'cloud_db')
        return instance

    def test_clouddbinstance(self):
        instance = self._setup_test_clouddbinstance('dbinstance')
        self.assertEqual(instance.hostname, None)
        self.assertEqual(instance.href, None)

    def test_clouddbinstance_create(self):
        instance = self._setup_test_clouddbinstance('dbinstance_create')
        fake_client = self.m.CreateMockAnything()
        instance.cloud_db().AndReturn(fake_client)
        fakedbinstance = FakeDBInstance()
        fake_client.create('Test',
                           flavor='1GB',
                           volume='30').AndReturn(fakedbinstance)
        self.m.ReplayAll()
        instance.handle_create()
        expected_hostname = fakedbinstance.hostname
        expected_href = fakedbinstance.links[0]['href']
        self.assertEqual(instance._resolve_attribute('hostname'),
                         expected_hostname)
        self.assertEqual(instance._resolve_attribute('href'), expected_href)
        self.m.VerifyAll()

    def test_clouddbinstance_delete_resource_notfound(self):
        instance = self._setup_test_clouddbinstance('dbinstance_delete')
        instance.resource_id = None
        self.m.ReplayAll()
        self.assertRaises(exception.ResourceNotFound, instance.handle_delete)
        self.m.VerifyAll()

    def test_clouddbinstance_delete(self):
        instance = self._setup_test_clouddbinstance('dbinstance_delete')
        fake_client = self.m.CreateMockAnything()
        cloud_db = instance.cloud_db().AndReturn(fake_client)
        fakedbinstance = FakeDBInstance()
        fake_client.delete(1234).AndReturn(None)
        self.m.ReplayAll()
        instance.handle_delete()
        self.m.VerifyAll()

    def test_clouddbinstance_param_validation_success(self):
        instance = self._setup_test_clouddbinstance(
            'dbinstance_params',
            inject_property_error=False)
        self.m.ReplayAll()
        ret = instance.validate()
        self.assertEqual(ret, None)
        self.m.VerifyAll()

    def test_clouddbinstance_param_validation_fail(self):
        instance = self._setup_test_clouddbinstance('dbinstance_params',
                                                    inject_property_error=True)
        self.m.ReplayAll()
        ret = instance.validate()
        self.assertTrue('Error' in ret)
        self.m.VerifyAll()
