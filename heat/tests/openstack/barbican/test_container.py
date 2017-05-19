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
from heat.engine.resources.openstack.barbican import container
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

stack_template_generic = '''
heat_template_version: 2015-10-15
description: Test template
resources:
  container:
    type: OS::Barbican::GenericContainer
    properties:
      name: mynewcontainer
      secrets:
        - name: secret1
          ref: ref1
        - name: secret2
          ref: ref2
'''

stack_template_certificate = '''
heat_template_version: 2015-10-15
description: Test template
resources:
  container:
    type: OS::Barbican::CertificateContainer
    properties:
      name: mynewcontainer
      certificate_ref: cref
      private_key_ref: pkref
      private_key_passphrase_ref: pkpref
      intermediates_ref: iref
'''

stack_template_rsa = '''
heat_template_version: 2015-10-15
description: Test template
resources:
  container:
    type: OS::Barbican::RSAContainer
    properties:
      name: mynewcontainer
      private_key_ref: pkref
      private_key_passphrase_ref: pkpref
      public_key_ref: pubref
'''


def template_by_name(name='OS::Barbican::GenericContainer'):
    mapping = {'OS::Barbican::GenericContainer': stack_template_generic,
               'OS::Barbican::CertificateContainer':
               stack_template_certificate,
               'OS::Barbican::RSAContainer': stack_template_rsa}
    return mapping[name]


class FakeContainer(object):

    def __init__(self, name):
        self.name = name

    def store(self):
        return self.name


class TestContainer(common.HeatTestCase):

    def setUp(self):
        super(TestContainer, self).setUp()

        self.patcher_client = mock.patch.object(
            container.GenericContainer, 'client')
        self.patcher_plugin = mock.patch.object(
            container.GenericContainer, 'client_plugin')
        mock_client = self.patcher_client.start()
        self.client = mock_client.return_value
        mock_plugin = self.patcher_plugin.start()
        self.client_plugin = mock_plugin.return_value
        self.stub_SecretConstraint_validate()

    def tearDown(self):
        super(TestContainer, self).tearDown()
        self.patcher_client.stop()
        self.patcher_plugin.stop()

    def _create_resource(self, name, snippet=None, stack=None,
                         tmpl_name='OS::Barbican::GenericContainer'):

        tmpl = template_format.parse(template_by_name(tmpl_name))
        if stack is None:
            self.stack = utils.parse_stack(tmpl)
        else:
            self.stack = stack
        resource_defns = self.stack.t.resource_definitions(self.stack)
        if snippet is None:
            snippet = resource_defns['container']
        res_class = container.resource_mapping()[tmpl_name]
        res = res_class(name, snippet, self.stack)
        res.check_create_complete = mock.Mock(return_value=True)
        create_generic_container = self.client_plugin.create_generic_container
        create_generic_container.return_value = FakeContainer('generic')
        self.client_plugin.create_certificate.return_value = FakeContainer(
            'certificate'
        )
        self.client_plugin.create_rsa.return_value = FakeContainer('rsa')
        scheduler.TaskRunner(res.create)()
        return res

    def test_create_generic(self):
        res = self._create_resource('foo')
        expected_state = (res.CREATE, res.COMPLETE)
        self.assertEqual(expected_state, res.state)
        args = self.client_plugin.create_generic_container.call_args[1]
        self.assertEqual('mynewcontainer', args['name'])
        self.assertEqual({'secret1': 'ref1', 'secret2': 'ref2'},
                         args['secret_refs'])
        self.assertEqual(sorted(['ref1', 'ref2']), sorted(res.get_refs()))

    def test_create_certificate(self):
        res = self._create_resource(
            'foo', tmpl_name='OS::Barbican::CertificateContainer')
        expected_state = (res.CREATE, res.COMPLETE)
        self.assertEqual(expected_state, res.state)
        args = self.client_plugin.create_certificate.call_args[1]
        self.assertEqual('mynewcontainer', args['name'])
        self.assertEqual('cref', args['certificate_ref'])
        self.assertEqual('pkref', args['private_key_ref'])
        self.assertEqual('pkpref', args['private_key_passphrase_ref'])
        self.assertEqual('iref', args['intermediates_ref'])
        self.assertEqual(sorted(['pkref', 'pkpref', 'iref', 'cref']),
                         sorted(res.get_refs()))

    def test_create_rsa(self):
        res = self._create_resource(
            'foo', tmpl_name='OS::Barbican::RSAContainer')
        expected_state = (res.CREATE, res.COMPLETE)
        self.assertEqual(expected_state, res.state)
        args = self.client_plugin.create_rsa.call_args[1]
        self.assertEqual('mynewcontainer', args['name'])
        self.assertEqual('pkref', args['private_key_ref'])
        self.assertEqual('pubref', args['public_key_ref'])
        self.assertEqual('pkpref', args['private_key_passphrase_ref'])
        self.assertEqual(sorted(['pkref', 'pubref', 'pkpref']),
                         sorted(res.get_refs()))

    def test_create_failed_on_validation(self):
        tmpl = template_format.parse(template_by_name())
        stack = utils.parse_stack(tmpl)
        props = tmpl['resources']['container']['properties']
        props['secrets'].append({'name': 'secret3', 'ref': 'ref1'})
        defn = rsrc_defn.ResourceDefinition(
            'failed_container', 'OS::Barbican::GenericContainer', props)
        res = container.GenericContainer('foo', defn, stack)
        self.assertRaisesRegex(exception.StackValidationFailed,
                               'Duplicate refs are not allowed',
                               res.validate)

    def test_attributes(self):
        mock_container = mock.Mock()
        mock_container.status = 'test-status'
        mock_container.container_ref = 'test-container-ref'
        mock_container.secret_refs = {'name': 'ref'}
        mock_container.consumers = [{'name': 'name1', 'ref': 'ref1'}]
        res = self._create_resource('foo')
        self.client.containers.get.return_value = mock_container
        self.assertEqual('test-status', res.FnGetAtt('status'))
        self.assertEqual('test-container-ref', res.FnGetAtt('container_ref'))
        self.assertEqual({'name': 'ref'}, res.FnGetAtt('secret_refs'))
        self.assertEqual([{'name': 'name1', 'ref': 'ref1'}],
                         res.FnGetAtt('consumers'))

    def test_check_create_complete(self):
        tmpl = template_format.parse(template_by_name())
        stack = utils.parse_stack(tmpl)
        resource_defns = stack.t.resource_definitions(stack)
        res_template = resource_defns['container']
        res = container.GenericContainer('foo', res_template, stack)
        mock_active = mock.Mock(status='ACTIVE')
        self.client.containers.get.return_value = mock_active
        self.assertTrue(res.check_create_complete('foo'))
        mock_not_active = mock.Mock(status='PENDING')
        self.client.containers.get.return_value = mock_not_active
        self.assertFalse(res.check_create_complete('foo'))
        mock_not_active = mock.Mock(status='ERROR', error_reason='foo',
                                    error_status_code=500)
        self.client.containers.get.return_value = mock_not_active
        exc = self.assertRaises(exception.ResourceInError,
                                res.check_create_complete, 'foo')
        self.assertIn('foo', six.text_type(exc))
        self.assertIn('500', six.text_type(exc))
