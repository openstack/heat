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

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.barbican import secret
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

stack_template = '''
heat_template_version: 2013-05-23
description: Test template
resources:
  secret:
    type: OS::Barbican::Secret
    properties:
      name: foobar-secret
'''


class FakeSecret(object):

    def __init__(self, name):
        self.name = name

    def store(self):
        return self.name


class TestSecret(common.HeatTestCase):

    def setUp(self):
        super(TestSecret, self).setUp()

        self.patcher_client = mock.patch.object(secret.Secret, 'client')
        mock_client = self.patcher_client.start()
        self.barbican = mock_client.return_value

        self.stack = utils.parse_stack(template_format.parse(stack_template))
        self.stack.validate()
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.res_template = resource_defns['secret']
        self.res = self._create_resource('foo', self.res_template, self.stack)

    def tearDown(self):
        super(TestSecret, self).tearDown()
        self.patcher_client.stop()

    def _create_resource(self, name, snippet, stack):
        res = secret.Secret(name, snippet, stack)
        self.barbican.secrets.create.return_value = FakeSecret(name + '_id')
        scheduler.TaskRunner(res.create)()
        return res

    def test_create_secret(self):
        expected_state = (self.res.CREATE, self.res.COMPLETE)
        self.assertEqual(expected_state, self.res.state)
        args = self.barbican.secrets.create.call_args[1]
        self.assertEqual('foobar-secret', args['name'])
        self.assertEqual('opaque', args['secret_type'])

    def test_attributes(self):
        mock_secret = mock.Mock()
        mock_secret.status = 'test-status'
        self.barbican.secrets.get.return_value = mock_secret
        mock_secret.payload = 'foo'

        self.assertEqual('test-status', self.res.FnGetAtt('status'))
        self.assertEqual('foo', self.res.FnGetAtt('decrypted_payload'))

    def test_attributes_handles_exceptions(self):
        self.barbican.barbican_client.HTTPClientError = Exception
        self.barbican.secrets.get.side_effect = Exception('boom')
        self.assertRaises(self.barbican.barbican_client.HTTPClientError,
                          self.res.FnGetAtt, 'order_ref')

    def test_create_secret_sets_resource_id(self):
        self.assertEqual('foo_id', self.res.resource_id)

    def test_create_secret_with_plain_text(self):
        content_type = 'text/plain'
        props = {
            'name': 'secret',
            'payload': 'foobar',
            'payload_content_type': content_type,
        }
        defn = rsrc_defn.ResourceDefinition('secret',
                                            'OS::Barbican::Secret',
                                            props)
        res = self._create_resource(defn.name, defn, self.stack)

        args = self.barbican.secrets.create.call_args[1]
        self.assertEqual('foobar', args[res.PAYLOAD])
        self.assertEqual(content_type, args[res.PAYLOAD_CONTENT_TYPE])

    def test_create_secret_with_octet_stream(self):
        content_type = 'application/octet-stream'
        props = {
            'name': 'secret',
            'payload': 'foobar',
            'payload_content_type': content_type,
        }
        defn = rsrc_defn.ResourceDefinition('secret',
                                            'OS::Barbican::Secret',
                                            props)
        res = self._create_resource(defn.name, defn, self.stack)

        args = self.barbican.secrets.create.call_args[1]
        self.assertEqual('foobar', args[res.PAYLOAD])
        self.assertEqual(content_type, args[res.PAYLOAD_CONTENT_TYPE])

    def test_create_secret_other_content_types_not_allowed(self):
        props = {
            'name': 'secret',
            'payload_content_type': 'not/allowed',
        }
        defn = rsrc_defn.ResourceDefinition('secret',
                                            'OS::Barbican::Secret',
                                            props)
        self.assertRaises(exception.ResourceFailure,
                          self._create_resource, defn.name, defn,
                          self.stack)

    def test_validate_content_type_without_payload(self):
        props = {
            'name': 'secret',
            'payload_content_type': 'text/plain',
        }
        defn = rsrc_defn.ResourceDefinition('secret',
                                            'OS::Barbican::Secret',
                                            props)
        res = self._create_resource(defn.name, defn, self.stack)
        msg = "payload_content_type cannot be specified without payload."
        self.assertRaisesRegex(exception.ResourcePropertyDependency,
                               msg, res.validate)

    def test_validate_octet_stream_without_encoding(self):
        props = {
            'name': 'secret',
            'payload': 'foobar',
            'payload_content_type': 'application/octet-stream',
        }
        defn = rsrc_defn.ResourceDefinition('secret',
                                            'OS::Barbican::Secret',
                                            props)
        res = self._create_resource(defn.name, defn, self.stack)
        msg = ("Property unspecified. For 'application/octet-stream' value of "
               "'payload_content_type' property, 'payload_content_encoding' "
               "property must be specified.")
        self.assertRaisesRegex(exception.StackValidationFailed,
                               msg, res.validate)

    def test_validate_base64(self):
        props = {
            'name': 'secret',
            'payload': 'foobar',
            'payload_content_type': 'application/octet-stream',
            'payload_content_encoding': 'base64'
        }
        defn = rsrc_defn.ResourceDefinition('secret',
                                            'OS::Barbican::Secret',
                                            props)
        res = self._create_resource(defn.name, defn, self.stack)
        msg = ("Invalid payload for specified 'base64' value of "
               "'payload_content_encoding' property.")
        self.assertRaisesRegex(exception.StackValidationFailed,
                               msg, res.validate)

    def test_validate_encoding_dependency(self):
        props = {
            'name': 'secret',
            'payload': 'foobar',
            'payload_content_type': 'text/plain',
            'payload_content_encoding': 'base64'
        }
        defn = rsrc_defn.ResourceDefinition('secret',
                                            'OS::Barbican::Secret',
                                            props)
        res = self._create_resource(defn.name, defn, self.stack)
        msg = ("payload_content_encoding property should only be specified "
               "for payload_content_type with value "
               "application/octet-stream.")
        self.assertRaisesRegex(exception.ResourcePropertyValueDependency,
                               msg, res.validate)
