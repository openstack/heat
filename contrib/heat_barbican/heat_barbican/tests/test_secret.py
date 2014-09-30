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

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils

from .. import client  # noqa
from ..resources import secret  # noqa

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


class TestSecret(HeatTestCase):

    def setUp(self):
        super(TestSecret, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()

        self.patcher_client = mock.patch.object(secret.Secret, 'barbican')
        mock_client = self.patcher_client.start()
        self.barbican = mock_client.return_value

        self._register_resources()
        self.stack = utils.parse_stack(template_format.parse(stack_template))
        self.stack.validate()
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.res_template = resource_defns['secret']
        self.res = self._create_resource('foo', self.res_template, self.stack)

    def tearDown(self):
        super(TestSecret, self).tearDown()
        self.patcher_client.stop()

    def _register_resources(self):
        for res_name, res_class in six.iteritems(secret.resource_mapping()):
            resource._register_class(res_name, res_class)

    def _create_resource(self, name, snippet, stack):
        res = secret.Secret(name, snippet, stack)
        self.barbican.secrets.Secret.return_value = FakeSecret(name + '_id')
        scheduler.TaskRunner(res.create)()
        return res

    def test_create_secret(self):
        expected_state = (self.res.CREATE, self.res.COMPLETE)
        self.assertEqual(expected_state, self.res.state)
        args = self.barbican.secrets.Secret.call_args[1]
        self.assertEqual('foobar-secret', args['name'])

    def test_attributes(self):
        mock_secret = mock.Mock()
        mock_secret.status = 'test-status'
        self.barbican.secrets.Secret.return_value = mock_secret
        mock_secret.payload = 'foo'

        self.assertEqual('test-status', self.res.FnGetAtt('status'))
        self.assertEqual('foo', self.res.FnGetAtt('decrypted_payload'))

    def test_attributes_handles_exceptions(self):
        self.barbican.barbican_client.HTTPClientError = Exception
        self.barbican.secrets.Secret.side_effect = Exception('boom')
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

        args = self.barbican.secrets.Secret.call_args[1]
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

        args = self.barbican.secrets.Secret.call_args[1]
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

    def test_validate_payload_and_content_type(self):
        props = {'payload_content_type': 'text/plain'}
        defn = rsrc_defn.ResourceDefinition('nopayload',
                                            'OS::Barbican::Secret',
                                            props)
        res = self._create_resource(defn.name, defn, self.stack)
        exc = self.assertRaises(exception.StackValidationFailed, res.validate)
        self.assertIn('payload', six.text_type(exc))
        self.assertIn('payload_content_type', six.text_type(exc))

        defn = rsrc_defn.ResourceDefinition('notype', 'OS::Barbican::Secret',
                                            {'payload': 'foo'})
        res = self._create_resource(defn.name, defn, self.stack)
        exc = self.assertRaises(exception.StackValidationFailed, res.validate)
        self.assertIn('payload', six.text_type(exc))
        self.assertIn('payload_content_type', six.text_type(exc))

    def test_delete_secret(self):
        self.assertEqual('foo_id', self.res.resource_id)

        mock_delete = self.barbican.secrets.delete
        scheduler.TaskRunner(self.res.delete)()

        mock_delete.assert_called_once_with('foo_id')

    def test_handle_delete_ignores_not_found_errors(self):
        self.barbican.barbican_client.HTTPClientError = Exception
        exc = self.barbican.barbican_client.HTTPClientError('Not Found.')
        self.barbican.secrets.delete.side_effect = exc
        scheduler.TaskRunner(self.res.delete)()
        self.assertTrue(self.barbican.secrets.delete.called)

    def test_handle_delete_raises_resource_failure_on_error(self):
        self.barbican.barbican_client.HTTPClientError = Exception
        exc = self.barbican.barbican_client.HTTPClientError('Boom.')
        self.barbican.secrets.delete.side_effect = exc
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(self.res.delete))
        self.assertIn('Boom.', six.text_type(exc))
