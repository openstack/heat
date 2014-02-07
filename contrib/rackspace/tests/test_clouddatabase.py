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

import uuid

from heat.common import template_format
from heat.engine import parser
from heat.engine import environment
from heat.engine import resource
from heat.tests.common import HeatTestCase
from heat.tests import utils

from ..resources import clouddatabase  # noqa

try:
    from pyrax.exceptions import ClientException
except ImportError:
    from ..resources.clouddatabase import ClientException  # noqa

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
        utils.setup_dummy_db()
        # Test environment may not have pyrax client library installed and if
        # pyrax is not installed resource class would not be registered.
        # So register resource provider class explicitly for unit testing.
        resource._register_class("Rackspace::Cloud::DBInstance",
                                 clouddatabase.CloudDBInstance)

    def _setup_test_clouddbinstance(self, name, inject_property_error=False):
        stack_name = '%s_stack' % name
        t = template_format.parse(wp_template)
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(),
                             stack_name,
                             template,
                             environment.Environment({'InstanceName': 'Test',
                                                      'FlavorRef': '1GB',
                                                      'VolumeSize': '30'}),
                             stack_id=str(uuid.uuid4()))

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
        self.assertIsNone(instance.hostname)
        self.assertIsNone(instance.href)

    def test_clouddbinstance_create(self):
        instance = self._setup_test_clouddbinstance('dbinstance_create')
        fake_client = self.m.CreateMockAnything()
        instance.cloud_db().AndReturn(fake_client)
        fakedbinstance = FakeDBInstance()
        fake_client.create('Test',
                           flavor='1GB',
                           volume=30).AndReturn(fakedbinstance)
        self.m.ReplayAll()
        instance.handle_create()
        expected_hostname = fakedbinstance.hostname
        expected_href = fakedbinstance.links[0]['href']
        self.assertEqual(expected_hostname,
                         instance._resolve_attribute('hostname'))
        self.assertEqual(expected_href, instance._resolve_attribute('href'))
        self.m.VerifyAll()

    def test_clouddbinstance_delete_resource_notfound(self):
        instance = self._setup_test_clouddbinstance('dbinstance_delete')
        instance.resource_id = None
        self.m.ReplayAll()
        instance.handle_delete()
        self.m.VerifyAll()

    def test_cloudbinstance_delete_exception(self):
        instance = self._setup_test_clouddbinstance('dbinstance_delete')
        fake_client = self.m.CreateMockAnything()
        instance.cloud_db().AndReturn(fake_client)
        client_exc = ClientException(404)
        fake_client.delete(instance.resource_id).AndRaise(client_exc)
        self.m.ReplayAll()
        instance.handle_delete()
        self.m.VerifyAll()

    def test_attribute_not_found(self):
        instance = self._setup_test_clouddbinstance('dbinstance_create')
        fake_client = self.m.CreateMockAnything()
        instance.cloud_db().AndReturn(fake_client)
        fakedbinstance = FakeDBInstance()
        fake_client.create('Test',
                           flavor='1GB',
                           volume=30).AndReturn(fakedbinstance)
        self.m.ReplayAll()
        instance.handle_create()
        self.assertIsNone(instance._resolve_attribute('invalid-attrib'))
        self.m.VerifyAll()

    def test_clouddbinstance_delete(self):
        instance = self._setup_test_clouddbinstance('dbinstance_delete')
        fake_client = self.m.CreateMockAnything()
        instance.cloud_db().AndReturn(fake_client)
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
        self.assertIsNone(ret)
        self.m.VerifyAll()

    def test_clouddbinstance_param_validation_fail(self):
        instance = self._setup_test_clouddbinstance('dbinstance_params',
                                                    inject_property_error=True)
        self.m.ReplayAll()
        ret = instance.validate()
        self.assertIn('Error', ret)
        self.m.VerifyAll()
