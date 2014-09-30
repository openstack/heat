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
from ..resources import order  # noqa

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
'''


class FakeOrder(object):

    def __init__(self, name):
        self.name = name

    def submit(self):
        return self.name


class TestOrder(HeatTestCase):

    def setUp(self):
        super(TestOrder, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()
        tmpl = template_format.parse(stack_template)
        self.stack = utils.parse_stack(tmpl)

        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.res_template = resource_defns['order']
        self.props = tmpl['resources']['order']['properties']
        self._register_resources()

        self.patcher_client = mock.patch.object(order.Order, 'barbican')
        mock_client = self.patcher_client.start()
        self.barbican = mock_client.return_value

    def tearDown(self):
        super(TestOrder, self).tearDown()
        self.patcher_client.stop()

    def _register_resources(self):
        for res_name, res_class in six.iteritems(order.resource_mapping()):
            resource._register_class(res_name, res_class)

    def _create_resource(self, name, snippet, stack):
        res = order.Order(name, snippet, stack)
        res.check_create_complete = mock.Mock(return_value=True)
        self.barbican.orders.Order.return_value = FakeOrder(name)
        scheduler.TaskRunner(res.create)()
        return res

    def test_create_order(self):
        res = self._create_resource('foo', self.res_template, self.stack)
        expected_state = (res.CREATE, res.COMPLETE)
        self.assertEqual(expected_state, res.state)
        args = self.barbican.orders.Order.call_args[1]
        self.assertEqual('foobar-order', args['name'])
        self.assertEqual('aes', args['algorithm'])
        self.assertEqual('cbc', args['mode'])
        self.assertEqual(256, args['bit_length'])

    def test_attributes(self):
        mock_order = mock.Mock()
        mock_order.status = 'test-status'
        mock_order.order_ref = 'test-order-ref'
        mock_order.secret_ref = 'test-secret-ref'

        res = self._create_resource('foo', self.res_template, self.stack)
        self.barbican.orders.Order.return_value = mock_order

        self.assertEqual('test-order-ref', res.FnGetAtt('order_ref'))
        self.assertEqual('test-secret-ref', res.FnGetAtt('secret_ref'))

    def test_attributes_handle_exceptions(self):
        mock_order = mock.Mock()
        res = self._create_resource('foo', self.res_template, self.stack)
        self.barbican.orders.Order.return_value = mock_order

        self.barbican.barbican_client.HTTPClientError = Exception
        self.barbican.orders.Order.side_effect = Exception('boom')
        self.assertRaises(self.barbican.barbican_client.HTTPClientError,
                          res.FnGetAtt, 'order_ref')

    def test_create_order_sets_resource_id(self):
        self.barbican.orders.Order.return_value = FakeOrder('foo')
        res = self._create_resource('foo', self.res_template, self.stack)

        self.assertEqual('foo', res.resource_id)

    def test_create_order_defaults_to_octet_stream(self):
        res = self._create_resource('foo', self.res_template, self.stack)

        args = self.barbican.orders.Order.call_args[1]
        self.assertEqual('application/octet-stream',
                         args[res.PAYLOAD_CONTENT_TYPE])

    def test_create_order_with_octet_stream(self):
        content_type = 'application/octet-stream'
        self.props['payload_content_type'] = content_type
        defn = rsrc_defn.ResourceDefinition('foo', 'OS::Barbican::Order',
                                            self.props)
        res = self._create_resource(defn.name, defn, self.stack)

        args = self.barbican.orders.Order.call_args[1]
        self.assertEqual(content_type, args[res.PAYLOAD_CONTENT_TYPE])

    def test_create_order_other_content_types_now_allowed(self):
        self.props['payload_content_type'] = 'not/allowed'
        defn = rsrc_defn.ResourceDefinition('order', 'OS::Barbican::Order',
                                            self.props)
        res = order.Order(defn.name, defn, self.stack)

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.create))

    def test_delete_order(self):
        self.barbican.orders.Order.return_value = 'foo'
        res = self._create_resource('foo', self.res_template, self.stack)
        self.assertEqual('foo', res.resource_id)

        scheduler.TaskRunner(res.delete)()
        self.barbican.orders.delete.assert_called_once_with('foo')

    def test_handle_delete_ignores_not_found_errors(self):
        res = self._create_resource('foo', self.res_template, self.stack)

        self.barbican.barbican_client.HTTPClientError = Exception
        exc = self.barbican.barbican_client.HTTPClientError('Not Found. Nope.')
        self.barbican.orders.delete.side_effect = exc
        scheduler.TaskRunner(res.delete)()
        self.assertTrue(self.barbican.orders.delete.called)

    def test_handle_delete_raises_resource_failure_on_error(self):
        res = self._create_resource('foo', self.res_template, self.stack)

        self.barbican.barbican_client.HTTPClientError = Exception
        exc = self.barbican.barbican_client.HTTPClientError('Boom.')
        self.barbican.orders.delete.side_effect = exc
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.delete))
        self.assertIn('Boom.', six.text_type(exc))

    def test_check_create_complete(self):
        res = order.Order('foo', self.res_template, self.stack)

        mock_active = mock.Mock(status='ACTIVE')
        self.barbican.orders.Order.return_value = mock_active
        self.assertTrue(res.check_create_complete('foo'))

        mock_not_active = mock.Mock(status='PENDING')
        self.barbican.orders.Order.return_value = mock_not_active
        self.assertFalse(res.check_create_complete('foo'))

        mock_not_active = mock.Mock(status='ERROR', error_reason='foo',
                                    error_status_code=500)
        self.barbican.orders.Order.return_value = mock_not_active
        exc = self.assertRaises(exception.Error,
                                res.check_create_complete, 'foo')
        self.assertIn('foo', six.text_type(exc))
        self.assertIn('500', six.text_type(exc))
