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
import six
import swiftclient.client as sc

from heat.common import exception
from heat.common import template_format
from heat.engine import node_data
from heat.engine.resources.openstack.swift import container as swift_c
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


SWIFT_TEMPLATE = '''
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


class SwiftTest(common.HeatTestCase):

    def setUp(self):
        super(SwiftTest, self).setUp()
        self.t = template_format.parse(SWIFT_TEMPLATE)

    def _create_container(self, stack, definition_name='SwiftContainer'):
        resource_defns = stack.t.resource_definitions(stack)
        container = swift_c.SwiftContainer('test_resource',
                                           resource_defns[definition_name],
                                           stack)
        runner = scheduler.TaskRunner(container.create)
        runner()
        self.assertEqual((container.CREATE, container.COMPLETE),
                         container.state)
        return container

    @mock.patch('swiftclient.client.Connection.put_container')
    def test_create_container_name(self, mock_put):
        # Setup
        res_prop = self.t['Resources']['SwiftContainer']['Properties']
        res_prop['name'] = 'the_name'
        stack = utils.parse_stack(self.t)

        # Test
        container = self._create_container(stack)
        container_name = container.physical_resource_name()

        # Verify
        self.assertEqual('the_name', container_name)
        mock_put.assert_called_once_with('the_name', {})

    def test_build_meta_headers(self):
        # Setup
        headers = {'Web-Index': 'index.html', 'Web-Error': 'error.html'}

        # Test
        self.assertEqual({}, swift_c.SwiftContainer._build_meta_headers(
            'container', {}))
        self.assertEqual({}, swift_c.SwiftContainer._build_meta_headers(
            'container', None))
        built = swift_c.SwiftContainer._build_meta_headers(
            'container', headers)

        # Verify
        expected = {
            'X-Container-Meta-Web-Index': 'index.html',
            'X-Container-Meta-Web-Error': 'error.html'
        }
        self.assertEqual(expected, built)

    @mock.patch('swiftclient.client.Connection.head_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_attributes(self, mock_put, mock_head):
        # Setup
        headers = {'content-length': '0',
                   'x-container-object-count': '82',
                   'accept-ranges': 'bytes',
                   'x-trans-id': 'tx08ea48ef2fa24e6da3d2f5c188fd938b',
                   'date': 'Wed, 23 Jan 2013 22:48:05 GMT',
                   'x-timestamp': '1358980499.84298',
                   'x-container-read': '.r:*',
                   'x-container-bytes-used': '17680980',
                   'content-type': 'text/plain; charset=utf-8'}
        mock_head.return_value = headers

        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        # Test
        container = self._create_container(stack)

        # call this to populate the url of swiftclient. This is actually
        # set in head_container/put_container, but we're patching them in
        # this test.
        container.client().get_auth()

        # Verify Attributes
        self.assertEqual(container_name, container.FnGetRefId())
        self.assertEqual('82', container.FnGetAtt('ObjectCount'))
        self.assertEqual('17680980', container.FnGetAtt('BytesUsed'))
        self.assertEqual('server.test', container.FnGetAtt('DomainName'))
        self.assertEqual(headers, container.FnGetAtt('HeadContainer'))
        self.assertEqual(headers, container.FnGetAtt('show'))

        expected_url = 'http://server.test:5000/v3/%s' % container.FnGetRefId()
        self.assertEqual(expected_url, container.FnGetAtt('WebsiteURL'))

        self.assertRaises(exception.InvalidTemplateAttribute,
                          container.FnGetAtt, 'Foo')

        # Verify Expected Calls
        mock_put.assert_called_once_with(container_name, {})
        self.assertGreater(mock_head.call_count, 0)

    @mock.patch('swiftclient.client.Connection.put_container')
    def test_public_read(self, mock_put):
        # Setup
        properties = self.t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        # Test
        self._create_container(stack)

        # Verify
        expected = {'X-Container-Read': '.r:*'}
        mock_put.assert_called_once_with(container_name, expected)

    @mock.patch('swiftclient.client.Connection.put_container')
    def test_public_read_write(self, mock_put):
        # Setup
        properties = self.t['Resources']['SwiftContainer']['Properties']
        properties['X-Container-Read'] = '.r:*'
        properties['X-Container-Write'] = '.r:*'
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        # Test
        self._create_container(stack)

        # Verify
        expected = {'X-Container-Write': '.r:*', 'X-Container-Read': '.r:*'}
        mock_put.assert_called_once_with(container_name, expected)

    @mock.patch('swiftclient.client.Connection.put_container')
    def test_container_headers(self, mock_put):
        # Setup
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        # Test
        self._create_container(stack,
                               definition_name='SwiftContainerWebsite')

        # Verify
        expected = {'X-Container-Meta-Web-Error': 'error.html',
                    'X-Container-Meta-Web-Index': 'index.html',
                    'X-Container-Read': '.r:*'}
        mock_put.assert_called_once_with(container_name, expected)

    @mock.patch('swiftclient.client.Connection.post_account')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_account_headers(self, mock_put, mock_post):
        # Setup
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        # Test
        self._create_container(stack,
                               definition_name='SwiftAccountMetadata')

        # Verify
        mock_put.assert_called_once_with(container_name, {})
        expected = {'X-Account-Meta-Temp-Url-Key': 'secret'}
        mock_post.assert_called_once_with(expected)

    @mock.patch('swiftclient.client.Connection.put_container')
    def test_default_headers_not_none_empty_string(self, mock_put):
        # Setup
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        # Test
        container = self._create_container(stack)

        # Verify
        mock_put.assert_called_once_with(container_name, {})
        self.assertEqual({}, container.metadata_get())

    @mock.patch('swiftclient.client.Connection.delete_container')
    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_delete_exception(self, mock_put, mock_get, mock_delete):
        # Setup
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        mock_delete.side_effect = sc.ClientException('test-delete-failure')
        mock_get.return_value = ({'name': container_name}, [])

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.delete)
        self.assertRaises(exception.ResourceFailure, runner)

        # Verify
        self.assertEqual((container.DELETE, container.FAILED),
                         container.state)
        mock_put.assert_called_once_with(container_name, {})
        mock_get.assert_called_once_with(container_name)
        mock_delete.assert_called_once_with(container_name)

    @mock.patch('swiftclient.client.Connection.delete_container')
    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_delete_not_found(self, mock_put, mock_get, mock_delete):
        # Setup
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        mock_delete.side_effect = sc.ClientException('missing',
                                                     http_status=404)
        mock_get.return_value = ({'name': container_name}, [])

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.delete)
        runner()

        # Verify
        self.assertEqual((container.DELETE, container.COMPLETE),
                         container.state)
        mock_put.assert_called_once_with(container_name, {})
        mock_get.assert_called_once_with(container_name)
        mock_delete.assert_called_once_with(container_name)

    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_delete_non_empty_not_allowed(self, mock_put, mock_get):
        # Setup
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        mock_get.return_value = ({'name': container_name},
                                 [{'name': 'test_object'}])

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.delete)
        ex = self.assertRaises(exception.ResourceFailure, runner)

        # Verify
        self.assertEqual((container.DELETE, container.FAILED),
                         container.state)
        self.assertIn('ResourceActionNotSupported: resources.test_resource: '
                      'Deleting non-empty container',
                      six.text_type(ex))
        mock_put.assert_called_once_with(container_name, {})
        mock_get.assert_called_once_with(container_name)

    @mock.patch('swiftclient.client.Connection.delete_container')
    @mock.patch('swiftclient.client.Connection.delete_object')
    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_delete_non_empty_allowed(self, mock_put, mock_get,
                                      mock_delete_object,
                                      mock_delete_container):
        # Setup
        res_prop = self.t['Resources']['SwiftContainer']['Properties']
        res_prop['PurgeOnDelete'] = True
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        get_return_values = [
            ({'name': container_name},
             [{'name': 'test_object1'},
              {'name': 'test_object2'}]),
            ({'name': container_name}, [{'name': 'test_object1'}]),
        ]
        mock_get.side_effect = get_return_values

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.delete)
        runner()

        # Verify
        self.assertEqual((container.DELETE, container.COMPLETE),
                         container.state)
        mock_put.assert_called_once_with(container_name, {})
        mock_delete_container.assert_called_once_with(container_name)
        self.assertEqual(2, mock_get.call_count)
        self.assertEqual(2, mock_delete_object.call_count)

    @mock.patch('swiftclient.client.Connection.delete_container')
    @mock.patch('swiftclient.client.Connection.delete_object')
    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_delete_non_empty_allowed_not_found(self, mock_put, mock_get,
                                                mock_delete_object,
                                                mock_delete_container):
        # Setup
        res_prop = self.t['Resources']['SwiftContainer']['Properties']
        res_prop['PurgeOnDelete'] = True
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        mock_get.return_value = ({'name': container_name},
                                 [{'name': 'test_object'}])
        mock_delete_object.side_effect = sc.ClientException('object-is-gone',
                                                            http_status=404)
        mock_delete_container.side_effect = sc.ClientException(
            'container-is-gone', http_status=404)

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.delete)
        runner()

        # Verify
        self.assertEqual((container.DELETE, container.COMPLETE),
                         container.state)
        mock_put.assert_called_once_with(container_name, {})
        mock_get.assert_called_once_with(container_name)
        mock_delete_object.assert_called_once_with(container_name,
                                                   'test_object')
        mock_delete_container.assert_called_once_with(container_name)

    @mock.patch('swiftclient.client.Connection.delete_object')
    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_delete_non_empty_fails_delete_object(self, mock_put, mock_get,
                                                  mock_delete_object):
        # Setup
        res_prop = self.t['Resources']['SwiftContainer']['Properties']
        res_prop['PurgeOnDelete'] = True
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        mock_get.return_value = ({'name': container_name},
                                 [{'name': 'test_object'}])
        mock_delete_object.side_effect = (
            sc.ClientException('object-delete-failure'))

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.delete)
        self.assertRaises(exception.ResourceFailure, runner)

        # Verify
        self.assertEqual((container.DELETE, container.FAILED),
                         container.state)
        mock_put.assert_called_once_with(container_name, {})
        mock_get.assert_called_once_with(container_name)
        mock_delete_object.assert_called_once_with(container_name,
                                                   'test_object')

    @mock.patch('swiftclient.client.Connection.put_container')
    def test_delete_retain(self, mock_put):
        # Setup
        self.t['Resources']['SwiftContainer']['DeletionPolicy'] = 'Retain'
        stack = utils.parse_stack(self.t)
        container_name = utils.PhysName(stack.name, 'test_resource')

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.delete)
        runner()

        # Verify
        self.assertEqual((container.DELETE, container.COMPLETE),
                         container.state)
        mock_put.assert_called_once_with(container_name, {})

    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_check(self, mock_put, mock_get):
        # Setup
        res_prop = self.t['Resources']['SwiftContainer']['Properties']
        res_prop['PurgeOnDelete'] = True
        stack = utils.parse_stack(self.t)

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.check)
        runner()
        self.assertEqual((container.CHECK, container.COMPLETE),
                         container.state)

    @mock.patch('swiftclient.client.Connection.get_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_check_fail(self, mock_put, mock_get):
        # Setup
        res_prop = self.t['Resources']['SwiftContainer']['Properties']
        res_prop['PurgeOnDelete'] = True
        stack = utils.parse_stack(self.t)

        mock_get.side_effect = Exception('boom')

        # Test
        container = self._create_container(stack)
        runner = scheduler.TaskRunner(container.check)
        ex = self.assertRaises(exception.ResourceFailure, runner)

        # Verify
        self.assertIn('boom', six.text_type(ex))
        self.assertEqual((container.CHECK, container.FAILED),
                         container.state)

    def test_refid(self):
        stack = utils.parse_stack(self.t)
        rsrc = stack['SwiftContainer']
        rsrc.resource_id = 'xyz'
        self.assertEqual('xyz', rsrc.FnGetRefId())

    def test_refid_convergence_cache_data(self):
        cache_data = {'SwiftContainer': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'xyz_convg'
        })}
        stack = utils.parse_stack(self.t, cache_data=cache_data)
        rsrc = stack.defn['SwiftContainer']
        self.assertEqual('xyz_convg', rsrc.FnGetRefId())

    @mock.patch('swiftclient.client.Connection.head_account')
    @mock.patch('swiftclient.client.Connection.head_container')
    @mock.patch('swiftclient.client.Connection.put_container')
    def test_parse_live_resource_data(self, mock_put, mock_container,
                                      mock_account):
        stack = utils.parse_stack(self.t)
        container = self._create_container(
            stack, definition_name="SwiftContainerWebsite")
        mock_container.return_value = {
            'x-container-read': '.r:*',
            'x-container-meta-web-index': 'index.html',
            'x-container-meta-web-error': 'error.html',
            'x-container-meta-login': 'login.html'
        }
        mock_account.return_value = {}
        live_state = container.parse_live_resource_data(
            container.properties, container.get_live_resource_data())
        # live state properties values should be equal to current resource
        # properties values
        self.assertEqual(dict(container.properties.items()), live_state)
