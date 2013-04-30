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


import os
import re

import unittest
import mox

from nose.plugins.attrib import attr

from heat.common import context
from heat.common import template_format
from heat.openstack.common.importutils import try_import
from heat.engine.resources import swift
from heat.engine import parser
from heat.engine import scheduler
from heat.tests.utils import skip_if

swiftclient = try_import('swiftclient.client')


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class swiftTest(unittest.TestCase):
    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def setUp(self):
        self.m = mox.Mox()
        self.m.CreateMock(swiftclient.Connection)
        self.m.StubOutWithMock(swiftclient.Connection, 'put_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'delete_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'head_container')
        self.m.StubOutWithMock(swiftclient.Connection, 'get_auth')

        self.container_pattern = 'test_stack-test_resource-[0-9a-z]+'

    def tearDown(self):
        self.m.UnsetStubs()
        print "swiftTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/Swift.template" % self.path)
        t = template_format.parse(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        ctx = context.RequestContext.from_dict({
            'tenant': 'test_tenant',
            'username': 'test_username',
            'password': 'password',
            'auth_url': 'http://localhost:5000/v2.0'})
        stack = parser.Stack(ctx, 'test_stack', parser.Template(t))

        return stack

    def create_resource(self, t, stack, resource_name):
        resource = swift.SwiftContainer(
            'test_resource',
            t['Resources'][resource_name],
            stack)
        scheduler.TaskRunner(resource.create)()
        self.assertEqual(swift.SwiftContainer.CREATE_COMPLETE, resource.state)
        return resource

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_create_container_name(self):
        self.m.ReplayAll()
        t = self.load_template()
        stack = self.parse_stack(t)
        resource = swift.SwiftContainer(
            'test_resource',
            t['Resources']['SwiftContainer'],
            stack)

        self.assertTrue(re.match(self.container_pattern,
                                 resource._create_container_name()))
        self.assertEqual(
            'the_name',
            resource._create_container_name('the_name'))

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_build_meta_headers(self):
        self.m.UnsetStubs()
        self.assertEqual({}, swift.SwiftContainer._build_meta_headers({}))
        self.assertEqual({}, swift.SwiftContainer._build_meta_headers(None))
        meta = {
            'X-Container-Meta-Web-Index': 'index.html',
            'X-Container-Meta-Web-Error': 'error.html'
        }
        self.assertEqual(meta, swift.SwiftContainer._build_meta_headers({
            "Web-Index": "index.html",
            "Web-Error": "error.html"
        }))

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_attributes(self):
        headers = {
            "content-length": "0",
            "x-container-object-count": "82",
            "x-container-write": "None",
            "accept-ranges": "bytes",
            "x-trans-id": "tx08ea48ef2fa24e6da3d2f5c188fd938b",
            "date": "Wed, 23 Jan 2013 22:48:05 GMT",
            "x-timestamp": "1358980499.84298",
            "x-container-read": ".r:*",
            "x-container-bytes-used": "17680980",
            "content-type": "text/plain; charset=utf-8"}

        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': None}
        ).AndReturn(None)
        swiftclient.Connection.get_auth().MultipleTimes().AndReturn(
            ('http://localhost:8080/v_2', None))
        swiftclient.Connection.head_container(
            mox.IgnoreArg()).MultipleTimes().AndReturn(headers)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = self.load_template()
        stack = self.parse_stack(t)
        resource = self.create_resource(t, stack, 'SwiftContainer')

        ref_id = resource.FnGetRefId()
        self.assertTrue(re.match(self.container_pattern,
                                 ref_id))

        self.assertEqual('localhost', resource.FnGetAtt('DomainName'))
        url = 'http://localhost:8080/v_2/%s' % ref_id

        self.assertEqual(url, resource.FnGetAtt('WebsiteURL'))
        self.assertEqual('82', resource.FnGetAtt('ObjectCount'))
        self.assertEqual('17680980', resource.FnGetAtt('BytesUsed'))
        self.assertEqual(headers, resource.FnGetAtt('HeadContainer'))

        try:
            resource.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except swift.exception.InvalidTemplateAttribute:
            pass

        self.assertEqual(swift.SwiftContainer.UPDATE_REPLACE,
                         resource.handle_update({}))

        resource.delete()
        self.m.VerifyAll()

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_public_read(self):
        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = self.load_template()
        properties = t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        stack = self.parse_stack(t)
        resource = self.create_resource(t, stack, 'SwiftContainer')
        resource.delete()
        self.m.VerifyAll()

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_public_read_write(self):
        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': '.r:*',
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = self.load_template()
        properties = t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        properties['X-Container-Write'] = '.r:*'
        stack = self.parse_stack(t)
        resource = self.create_resource(t, stack, 'SwiftContainer')
        resource.delete()
        self.m.VerifyAll()

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_website(self):

        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Meta-Web-Error': 'error.html',
             'X-Container-Meta-Web-Index': 'index.html',
             'X-Container-Write': None,
             'X-Container-Read': '.r:*'}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = self.load_template()
        stack = self.parse_stack(t)
        resource = self.create_resource(t, stack, 'SwiftContainerWebsite')
        resource.delete()
        self.m.VerifyAll()

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_delete_exception(self):

        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': None}).AndReturn(None)
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndRaise(
                swiftclient.ClientException('Test delete failure'))

        self.m.ReplayAll()
        t = self.load_template()
        stack = self.parse_stack(t)
        resource = self.create_resource(t, stack, 'SwiftContainer')
        resource.delete()

        self.m.VerifyAll()

    @skip_if(swiftclient is None, 'unable to import swiftclient')
    def test_delete_retain(self):

        # first run, with retain policy
        swiftclient.Connection.put_container(
            mox.Regex(self.container_pattern),
            {'X-Container-Write': None,
             'X-Container-Read': None}).AndReturn(None)
        # This should not be called
        swiftclient.Connection.delete_container(
            mox.Regex(self.container_pattern)).AndReturn(None)

        self.m.ReplayAll()
        t = self.load_template()

        properties = t['Resources']['SwiftContainer']['Properties']
        properties['DeletionPolicy'] = 'Retain'
        stack = self.parse_stack(t)
        resource = self.create_resource(t, stack, 'SwiftContainer')
        # if delete_container is called, mox verify will succeed
        resource.delete()

        try:
            self.m.VerifyAll()
        except mox.ExpectedMethodCallsError:
            return

        raise Exception('delete_container was called despite Retain policy')
