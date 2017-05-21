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
from heat.engine.resources.openstack.barbican import order
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

stack_template = '''
heat_template_version: 2013-05-23
description: Test template
resources:
  order:
    type: OS::Barbican::Order
    properties:
      name: foobar-order
      algorithm: aes
      bit_length: 256
      mode: cbc
      type: key
'''


class FakeOrder(object):

    def __init__(self, name):
        self.name = name

    def submit(self):
        return self.name


class TestOrder(common.HeatTestCase):

    def setUp(self):
        super(TestOrder, self).setUp()
        tmpl = template_format.parse(stack_template)
        self.stack = utils.parse_stack(tmpl)

        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.res_template = resource_defns['order']
        self.props = tmpl['resources']['order']['properties']

        self.patcher_client = mock.patch.object(order.Order, 'client')
        mock_client = self.patcher_client.start()
        self.barbican = mock_client.return_value

    def tearDown(self):
        super(TestOrder, self).tearDown()
        self.patcher_client.stop()

    def _create_resource(self, name, snippet, stack):
        res = order.Order(name, snippet, stack)
        res.check_create_complete = mock.Mock(return_value=True)
        self.barbican.orders.create.return_value = FakeOrder(name)
        scheduler.TaskRunner(res.create)()
        return res

    def test_create_order(self):
        res = self._create_resource('foo', self.res_template, self.stack)
        expected_state = (res.CREATE, res.COMPLETE)
        self.assertEqual(expected_state, res.state)
        args = self.barbican.orders.create.call_args[1]
        self.assertEqual('foobar-order', args['name'])
        self.assertEqual('aes', args['algorithm'])
        self.assertEqual('cbc', args['mode'])
        self.assertEqual(256, args['bit_length'])

    def test_create_order_without_type_fail(self):
        props = self.props.copy()
        del props['type']
        snippet = self.res_template.freeze(properties=props)

        self.assertRaisesRegex(exception.ResourceFailure,
                               'Property type not assigned',
                               self._create_resource,
                               'foo',
                               snippet, self.stack)

    def test_validate_non_certificate_order(self):
        props = self.props.copy()
        del props['bit_length']
        del props['algorithm']
        snippet = self.res_template.freeze(properties=props)
        res = self._create_resource('test', snippet, self.stack)
        msg = ("Properties algorithm and bit_length are required for "
               "key type of order.")
        self.assertRaisesRegex(exception.StackValidationFailed,
                               msg,
                               res.validate)

    def test_validate_certificate_with_profile_without_ca_id(self):
        props = self.props.copy()
        props['profile'] = 'cert'
        props['type'] = 'certificate'
        snippet = self.res_template.freeze(properties=props)
        res = self._create_resource('test', snippet, self.stack)
        msg = ("profile cannot be specified without ca_id.")
        self.assertRaisesRegex(exception.ResourcePropertyDependency,
                               msg,
                               res.validate)

    def test_key_order_validation_fail(self):
        props = self.props.copy()
        props['pass_phrase'] = "something"
        snippet = self.res_template.freeze(properties=props)
        res = self._create_resource('test', snippet, self.stack)
        msg = ("Unexpected properties: pass_phrase. Only these properties "
               "are allowed for key type of order: algorithm, "
               "bit_length, expiration, mode, name, payload_content_type.")
        self.assertRaisesRegex(exception.StackValidationFailed,
                               msg,
                               res.validate)

    def test_certificate_validation_fail(self):
        props = self.props.copy()
        props['type'] = 'certificate'
        snippet = self.res_template.freeze(properties=props)
        res = self._create_resource('test', snippet, self.stack)
        msg = ("Unexpected properties: algorithm, bit_length, mode. Only "
               "these properties are allowed for certificate type of order: "
               "ca_id, name, profile, request_data, request_type, "
               "source_container_ref, subject_dn.")
        self.assertRaisesRegex(exception.StackValidationFailed,
                               msg,
                               res.validate)

    def test_asymmetric_order_validation_fail(self):
        props = self.props.copy()
        props['type'] = 'asymmetric'
        props['subject_dn'] = 'asymmetric'
        snippet = self.res_template.freeze(properties=props)
        res = self._create_resource('test', snippet, self.stack)
        msg = ("Unexpected properties: subject_dn. Only these properties are "
               "allowed for asymmetric type of order: algorithm, bit_length, "
               "expiration, mode, name, pass_phrase, payload_content_type")
        self.assertRaisesRegex(exception.StackValidationFailed,
                               msg,
                               res.validate)

    def test_attributes(self):
        mock_order = mock.Mock()
        mock_order.status = 'test-status'
        mock_order.order_ref = 'test-order-ref'
        mock_order.secret_ref = 'test-secret-ref'

        res = self._create_resource('foo', self.res_template, self.stack)
        self.barbican.orders.get.return_value = mock_order

        self.assertEqual('test-order-ref', res.FnGetAtt('order_ref'))
        self.assertEqual('test-secret-ref', res.FnGetAtt('secret_ref'))

    def test_attributes_handle_exceptions(self):
        mock_order = mock.Mock()
        res = self._create_resource('foo', self.res_template, self.stack)
        self.barbican.orders.get.return_value = mock_order

        self.barbican.barbican_client.HTTPClientError = Exception
        self.barbican.orders.get.side_effect = Exception('boom')
        self.assertRaises(self.barbican.barbican_client.HTTPClientError,
                          res.FnGetAtt, 'order_ref')

    def test_container_attributes(self):
        mock_order = mock.Mock()
        mock_order.container_ref = 'test-container-ref'

        mock_container = mock.Mock()
        mock_container.public_key = mock.Mock(payload='public-key')
        mock_container.private_key = mock.Mock(payload='private-key')
        mock_container.certificate = mock.Mock(payload='cert')
        mock_container.intermediates = mock.Mock(payload='interm')

        res = self._create_resource('foo', self.res_template, self.stack)
        self.barbican.orders.get.return_value = mock_order

        self.barbican.containers.get.return_value = mock_container

        self.assertEqual('public-key', res.FnGetAtt('public_key'))
        self.barbican.containers.get.assert_called_once_with(
            'test-container-ref')

        self.assertEqual('private-key', res.FnGetAtt('private_key'))
        self.assertEqual('cert', res.FnGetAtt('certificate'))
        self.assertEqual('interm', res.FnGetAtt('intermediates'))

    def test_create_order_sets_resource_id(self):
        self.barbican.orders.create.return_value = FakeOrder('foo')
        res = self._create_resource('foo', self.res_template, self.stack)

        self.assertEqual('foo', res.resource_id)

    def test_create_order_with_octet_stream(self):
        content_type = 'application/octet-stream'
        self.props['payload_content_type'] = content_type
        defn = rsrc_defn.ResourceDefinition('foo', 'OS::Barbican::Order',
                                            self.props)
        res = self._create_resource(defn.name, defn, self.stack)

        args = self.barbican.orders.create.call_args[1]
        self.assertEqual(content_type, args[res.PAYLOAD_CONTENT_TYPE])

    def test_check_create_complete(self):
        res = order.Order('foo', self.res_template, self.stack)

        mock_active = mock.Mock(status='ACTIVE')
        self.barbican.orders.get.return_value = mock_active
        self.assertTrue(res.check_create_complete('foo'))

        mock_not_active = mock.Mock(status='PENDING')
        self.barbican.orders.get.return_value = mock_not_active
        self.assertFalse(res.check_create_complete('foo'))

        mock_not_active = mock.Mock(status='ERROR', error_reason='foo',
                                    error_status_code=500)
        self.barbican.orders.get.return_value = mock_not_active
        exc = self.assertRaises(exception.Error,
                                res.check_create_complete, 'foo')
        self.assertIn('foo', six.text_type(exc))
        self.assertIn('500', six.text_type(exc))
