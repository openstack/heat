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


import mock
import mox
import six
import swiftclient.client as sc

from heat.common import exception
from heat.common import template_format
from heat.engine.resources import swift
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


swift_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test OS::Swift::Container resources",
  "Resources" : {
    "SwiftContainerWebsite" : {
      "Type" : "OS::Swift::Container",
      "DeletionPolicy" : "Delete",
      "Properties" : {
        "X-Container-Read" : ".r:*",
        "X-Container-Meta" : {
          "Web-Index" : "index.html",
          "Web-Error" : "error.html"
}
      }
    },
    "SwiftAccountMetadata" : {
      "Type" : "OS::Swift::Container",
      "DeletionPolicy" : "Delete",
      "Properties" : {
        "X-Account-Meta" : {
          "Temp-Url-Key" : "secret"
         }
      }
    },
    "S3Bucket" : {
      "Type" : "AWS::S3::Bucket",
      "Properties" : {
        "SwiftContainer" : {"Ref" : "SwiftContainer"}
      }
    },
    "SwiftContainer" : {
      "Type" : "OS::Swift::Container",
      "Properties" : {
      }
    }
  }
}
'''


class swiftTest(common.HeatTestCase):
    def setUp(self):
        super(swiftTest, self).setUp()
        self.m.CreateMock(sc.Connection)
        self.m.StubOutWithMock(sc.Connection, 'post_account')
        self.m.StubOutWithMock(sc.Connection, 'put_container')
        self.m.StubOutWithMock(sc.Connection, 'get_container')
        self.m.StubOutWithMock(sc.Connection, 'delete_container')
        self.m.StubOutWithMock(sc.Connection, 'delete_object')
        self.m.StubOutWithMock(sc.Connection, 'head_container')
        self.m.StubOutWithMock(sc.Connection, 'get_auth')
        self.stub_auth()

    def create_resource(self, t, stack, resource_name):
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = swift.SwiftContainer(
            'test_resource',
            resource_defns[resource_name],
            stack)
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def stub_delete_empty(self, res_id):
        sc.Connection.get_container(res_id).AndReturn(
            ({'name': res_id}, []))
        sc.Connection.delete_container(res_id).AndReturn(None)

    def test_create_container_name(self):
        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        t['Resources']['SwiftContainer']['Properties']['name'] = 'the_name'
        stack = utils.parse_stack(t)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = swift.SwiftContainer(
            'test_resource',
            resource_defns['SwiftContainer'],
            stack)

        self.assertEqual('the_name', rsrc.physical_resource_name())

    def test_build_meta_headers(self):
        self.m.UnsetStubs()
        self.assertEqual({}, swift.SwiftContainer._build_meta_headers(
            'container', {}))
        self.assertEqual({}, swift.SwiftContainer._build_meta_headers(
            'container', None))
        meta = {
            'X-Container-Meta-Web-Index': 'index.html',
            'X-Container-Meta-Web-Error': 'error.html'
        }
        self.assertEqual(meta, swift.SwiftContainer._build_meta_headers(
            'container', {
                "Web-Index": "index.html",
                "Web-Error": "error.html"
            }))

    def test_attributes(self):
        headers = {
            "content-length": "0",
            "x-container-object-count": "82",
            "accept-ranges": "bytes",
            "x-trans-id": "tx08ea48ef2fa24e6da3d2f5c188fd938b",
            "date": "Wed, 23 Jan 2013 22:48:05 GMT",
            "x-timestamp": "1358980499.84298",
            "x-container-read": ".r:*",
            "x-container-bytes-used": "17680980",
            "content-type": "text/plain; charset=utf-8"}

        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name, {}).AndReturn(None)
        sc.Connection.head_container(
            mox.IgnoreArg()).MultipleTimes().AndReturn(headers)
        self.stub_delete_empty(container_name)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')

        ref_id = rsrc.FnGetRefId()
        self.assertEqual(container_name, ref_id)

        self.assertEqual('example.com', rsrc.FnGetAtt('DomainName'))
        url = 'http://example.com:1234/v1/%s' % ref_id

        self.assertEqual(url, rsrc.FnGetAtt('WebsiteURL'))
        self.assertEqual('82', rsrc.FnGetAtt('ObjectCount'))
        self.assertEqual('17680980', rsrc.FnGetAtt('BytesUsed'))
        self.assertEqual(headers, rsrc.FnGetAtt('HeadContainer'))

        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'Foo')

        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_public_read(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {'X-Container-Read': '.r:*'}).AndReturn(None)
        self.stub_delete_empty(container_name)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        properties = t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_public_read_write(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {'X-Container-Write': '.r:*',
             'X-Container-Read': '.r:*'}).AndReturn(None)
        self.stub_delete_empty(container_name)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        properties = t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        properties['X-Container-Write'] = '.r:*'
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_container_headers(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {'X-Container-Meta-Web-Error': 'error.html',
             'X-Container-Meta-Web-Index': 'index.html',
             'X-Container-Read': '.r:*'}).AndReturn(None)
        self.stub_delete_empty(container_name)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainerWebsite')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_account_headers(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(container_name, {})
        sc.Connection.post_account(
            {'X-Account-Meta-Temp-Url-Key': 'secret'}).AndReturn(None)
        self.stub_delete_empty(container_name)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftAccountMetadata')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

    def test_delete_exception(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {}).AndReturn(None)
        sc.Connection.get_container(
            container_name).AndReturn(({'name': container_name},
                                       []))
        sc.Connection.delete_container(container_name).AndRaise(
            sc.ClientException('Test delete failure'))

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.delete))

        self.m.VerifyAll()

    def test_delete_not_found(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {}).AndReturn(None)
        sc.Connection.get_container(
            container_name).AndReturn(({'name': container_name},
                                       []))
        sc.Connection.delete_container(container_name).AndRaise(
            sc.ClientException('Its gone',
                               http_status=404))

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        scheduler.TaskRunner(rsrc.delete)()

        self.m.VerifyAll()

    def test_delete_non_empty_not_allowed(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {}).AndReturn(None)
        sc.Connection.get_container(
            container_name).AndReturn(({'name': container_name},
                                       [{'name': 'test_object'}]))

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        deleter = scheduler.TaskRunner(rsrc.delete)
        ex = self.assertRaises(exception.ResourceFailure, deleter)
        self.assertIn('ResourceActionNotSupported: '
                      'Deleting non-empty container',
                      six.text_type(ex))

        self.m.VerifyAll()

    def test_delete_non_empty_allowed(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {}).AndReturn(None)
        sc.Connection.get_container(
            container_name).AndReturn(({'name': container_name},
                                       [{'name': 'test_object1'},
                                        {'name': 'test_object2'}]))
        sc.Connection.delete_object(container_name, 'test_object2'
                                    ).AndReturn(None)
        sc.Connection.get_container(
            container_name).AndReturn(({'name': container_name},
                                       [{'name': 'test_object1'}]))
        sc.Connection.delete_object(container_name, 'test_object1'
                                    ).AndReturn(None)
        sc.Connection.delete_container(container_name).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        t['Resources']['SwiftContainer']['Properties']['PurgeOnDelete'] = True
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_non_empty_allowed_ignores_not_found(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {}).AndReturn(None)
        sc.Connection.get_container(
            container_name).AndReturn(({'name': container_name},
                                       [{'name': 'test_object'}]))
        sc.Connection.delete_object(
            container_name, 'test_object').AndRaise(
                sc.ClientException('Object is gone', http_status=404))
        sc.Connection.delete_container(
            container_name).AndRaise(
                sc.ClientException('Container is gone', http_status=404))

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        t['Resources']['SwiftContainer']['Properties']['PurgeOnDelete'] = True
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_non_empty_fails_delete_object(self):
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name,
            {}).AndReturn(None)
        sc.Connection.get_container(
            container_name).AndReturn(({'name': container_name},
                                       [{'name': 'test_object'}]))
        sc.Connection.delete_object(
            container_name, 'test_object').AndRaise(
                sc.ClientException('Test object delete failure'))

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        t['Resources']['SwiftContainer']['Properties']['PurgeOnDelete'] = True
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.delete))
        self.m.VerifyAll()

    def _get_check_resource(self):
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        res = self.create_resource(t, stack, 'SwiftContainer')
        res.swift = mock.Mock()
        return res

    def test_check(self):
        res = self._get_check_resource()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_check_fail(self):
        res = self._get_check_resource()
        res.swift().get_container.side_effect = Exception('boom')

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.check))
        self.assertIn('boom', six.text_type(exc))
        self.assertEqual((res.CHECK, res.FAILED), res.state)

    def test_delete_retain(self):
        # first run, with retain policy
        sc.Connection.put_container(
            utils.PhysName('test_stack', 'test_resource'),
            {}).AndReturn(None)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)

        container = t['Resources']['SwiftContainer']
        container['DeletionPolicy'] = 'Retain'
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.m.VerifyAll()

    def test_default_headers_not_none_empty_string(self):
        '''Test that we are not passing None when we have a default
        empty string or sc will pass them as string None. see
        bug lp:1259571.
        '''
        container_name = utils.PhysName('test_stack', 'test_resource')
        sc.Connection.put_container(
            container_name, {}).AndReturn(None)
        self.stub_delete_empty(container_name)

        self.m.ReplayAll()
        t = template_format.parse(swift_template)
        stack = utils.parse_stack(t)
        rsrc = self.create_resource(t, stack, 'SwiftContainer')
        scheduler.TaskRunner(rsrc.delete)()
        self.m.VerifyAll()

        self.assertEqual({}, rsrc.metadata_get())
