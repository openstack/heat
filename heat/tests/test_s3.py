
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

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import resource
from heat.engine.resources import s3
from heat.engine import scheduler
from heat.openstack.common.importutils import try_import
from heat.tests.common import HeatTestCase
from heat.tests import fakes
from heat.tests import utils

swiftclient = try_import('swiftclient.client')

swift_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test S3 Bucket resources",
  "Resources" : {
    "S3BucketWebsite" : {
      "Type" : "AWS::S3::Bucket",
      "DeletionPolicy" : "Delete",
      "Properties" : {
        "AccessControl" : "PublicRead",
        "WebsiteConfiguration" : {
          "IndexDocument" : "index.html",
          "ErrorDocument" : "error.html"
         }
      }
    },
    "SwiftContainer": {
         "Type": "OS::Swift::Container",
         "Properties": {
            "S3Bucket": {"Ref" : "S3Bucket"},
         }
      },
    "S3Bucket" : {
      "Type" : "AWS::S3::Bucket",
      "Properties" : {
        "AccessControl" : "Private"
      }
    },
    "S3Bucket_with_tags" : {
      "Type" : "AWS::S3::Bucket",
      "Properties" : {
        "Tags" : [{"Key": "greeting", "Value": "hello"},
                  {"Key": "location", "Value": "here"}]
      }
    }
  }
}
'''


class s3Test(HeatTestCase):
    @skipIf(swiftclient is None, 'unable to import swiftclient')
    def setUp(self):
        super(s3Test, self).setUp()
        self.m.CreateMock(swiftclient.Connection)
        self.m.StubOutWithMock(swiftclient.Connection, 'put_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'delete_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'get_auth')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')

        utils.setup_dummy_db()

    def create_resource(self, t, stack, resource_name):
        rsrc = s3.S3Bucket('test_resource',
                           t['Resources'][resource_name],
                           stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_attributes(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        container_name = utils.PhysName('test_stack', 'test_resource')
        swiftclient.Connection.put_container(
            container_name,
            {'X-Container-Write': 'test_tenant:test_username',
             'X-Container-Read': 'test_tenant:test_username'}
        ).AndReturn(None)
        swiftclient.Connection.get_auth().MultipleTimes().AndReturn(
            ('http://server.test:8080/v_2', None))
        swiftclient.Connection.delete_container(container_name).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3Bucket')

        ref_id = rsrc.FnGetRefId()
        self.assertEqual(container_name, ref_id)

        self.assertEqual('server.test', rsrc.FnGetAtt('DomainName'))
        url = 'http://server.test:8080/v_2/%s' % ref_id

        self.assertEqual(url, rsrc.FnGetAtt('WebsiteURL'))

        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'Foo')

        self.assertRaises(resource.UpdateReplace,
                          rsrc.handle_update, {}, {}, {})

        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_public_read(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        container_name = utils.PhysName('test_stack', 'test_resource')
        swiftclient.Connection.put_container(
            utils.PhysName('test_stack', 'test_resource'),
            {'X-Container-Write': 'test_tenant:test_username',
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            container_name).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        properties = t['Resources']['S3Bucket']['Properties']
        properties['AccessControl'] = 'PublicRead'
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3Bucket')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_tags(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        container_name = utils.PhysName('test_stack', 'test_resource')
        swiftclient.Connection.put_container(
            utils.PhysName('test_stack', 'test_resource'),
            {'X-Container-Write': 'test_tenant:test_username',
             'X-Container-Read': 'test_tenant:test_username',
             'X-Container-Meta-S3-Tag-greeting': 'hello',
             'X-Container-Meta-S3-Tag-location': 'here'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            container_name).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3Bucket_with_tags')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_public_read_write(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        container_name = utils.PhysName('test_stack', 'test_resource')
        swiftclient.Connection.put_container(
            container_name,
            {'X-Container-Write': '.r:*',
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            container_name).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        properties = t['Resources']['S3Bucket']['Properties']
        properties['AccessControl'] = 'PublicReadWrite'
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3Bucket')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_authenticated_read(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        container_name = utils.PhysName('test_stack', 'test_resource')
        swiftclient.Connection.put_container(
            container_name,
            {'X-Container-Write': 'test_tenant:test_username',
             'X-Container-Read': 'test_tenant'}).AndReturn(None)
        swiftclient.Connection.delete_container(container_name).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        properties = t['Resources']['S3Bucket']['Properties']
        properties['AccessControl'] = 'AuthenticatedRead'
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3Bucket')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_website(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        container_name = utils.PhysName('test_stack', 'test_resource')
        swiftclient.Connection.put_container(
            container_name,
            {'X-Container-Meta-Web-Error': 'error.html',
             'X-Container-Meta-Web-Index': 'index.html',
             'X-Container-Write': 'test_tenant:test_username',
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(container_name).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3BucketWebsite')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_delete_exception(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        container_name = utils.PhysName('test_stack', 'test_resource')
        swiftclient.Connection.put_container(
            container_name,
            {'X-Container-Write': 'test_tenant:test_username',
             'X-Container-Read': 'test_tenant:test_username'}).AndReturn(None)
        swiftclient.Connection.delete_container(container_name).AndRaise(
            swiftclient.ClientException('Test delete failure'))

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3Bucket')
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_delete_retain(self):

        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        # first run, with retain policy
        swiftclient.Connection.put_container(
            utils.PhysName('test_stack', 'test_resource'),
            {'X-Container-Write': 'test_tenant:test_username',
             'X-Container-Read': 'test_tenant:test_username'}).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)

        bucket = t['Resources']['S3Bucket']
        bucket['DeletionPolicy'] = 'Retain'
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'S3Bucket')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()
