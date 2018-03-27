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

from neutronclient.common import exceptions
from neutronclient.v2_0 import client as neutronclient

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.neutron import metering
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


metering_template = '''
heat_template_version: 2015-04-30
description: Template to test metering resources
resources:
  label:
    type: OS::Neutron::MeteringLabel
    properties:
      name: TestLabel
      description: Description of TestLabel
      shared: True

  rule:
    type: OS::Neutron::MeteringRule
    properties:
      metering_label_id: { get_resource: label }
      remote_ip_prefix: 10.0.3.0/24
      direction: ingress
      excluded: false
'''


class MeteringLabelTest(common.HeatTestCase):

    def setUp(self):
        super(MeteringLabelTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

    def create_metering_label(self):
        self.mockclient.create_metering_label.return_value = {
            'metering_label': {'id': '1234'}
        }
        snippet = template_format.parse(metering_template)
        self.stack = utils.parse_stack(snippet)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return metering.MeteringLabel(
            'label', resource_defns['label'], self.stack)

    def test_create(self):
        rsrc = self.create_metering_label()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_metering_label.assert_called_once_with({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel',
                'shared': True
            }
        })

    def test_create_failed(self):
        self.mockclient.create_metering_label.side_effect = (
            exceptions.NeutronClientException())

        snippet = template_format.parse(metering_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = metering.MeteringLabel(
            'label', resource_defns['label'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.label: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_metering_label.assert_called_once_with({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel',
                'shared': True
            }
        })

    def test_delete(self):
        rsrc = self.create_metering_label()
        self.mockclient.delete_metering_label.return_value = None
        self.mockclient.show_metering_label.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_metering_label.assert_called_once_with({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel',
                'shared': True
            }
        })
        self.mockclient.delete_metering_label.assert_called_once_with('1234')
        self.mockclient.show_metering_label.assert_called_once_with('1234')

    def test_delete_already_gone(self):
        rsrc = self.create_metering_label()
        self.mockclient.delete_metering_label.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_metering_label.assert_called_once_with({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel',
                'shared': True
            }
        })
        self.mockclient.delete_metering_label.assert_called_once_with('1234')
        self.mockclient.show_metering_label.assert_not_called()

    def test_delete_failed(self):
        rsrc = self.create_metering_label()
        self.mockclient.delete_metering_label.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.label: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_metering_label.assert_called_once_with({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel',
                'shared': True
            }
        })
        self.mockclient.delete_metering_label.assert_called_once_with('1234')

    def test_attribute(self):
        rsrc = self.create_metering_label()
        self.mockclient.show_metering_label.return_value = {
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel',
                'shared': True
            }
        }

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('TestLabel', rsrc.FnGetAtt('name'))
        self.assertEqual('Description of TestLabel',
                         rsrc.FnGetAtt('description'))
        self.assertTrue(rsrc.FnGetAtt('shared'))

        self.mockclient.create_metering_label.assert_called_once_with({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel',
                'shared': True
            }
        })
        self.mockclient.show_metering_label.assert_called_with('1234')


class MeteringRuleTest(common.HeatTestCase):

    def setUp(self):
        super(MeteringRuleTest, self).setUp()
        self.mockclient = mock.Mock(spec=neutronclient.Client)
        self.patchobject(neutronclient, 'Client', return_value=self.mockclient)

    def create_metering_label_rule(self):
        self.mockclient.create_metering_label_rule.return_value = {
            'metering_label_rule': {'id': '5678'}
        }

        snippet = template_format.parse(metering_template)
        self.stack = utils.parse_stack(snippet)
        self.patchobject(self.stack['label'], 'FnGetRefId',
                         return_value='1234')
        resource_defns = self.stack.t.resource_definitions(self.stack)
        return metering.MeteringRule(
            'rule', resource_defns['rule'], self.stack)

    def test_create(self):
        rsrc = self.create_metering_label_rule()

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_metering_label_rule.assert_called_once_with({
            'metering_label_rule': {
                'metering_label_id': '1234',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False
            }
        })

    def test_create_failed(self):
        self.mockclient.create_metering_label_rule.side_effect = (
            exceptions.NeutronClientException())

        snippet = template_format.parse(metering_template)
        stack = utils.parse_stack(snippet)
        self.patchobject(stack['label'], 'FnGetRefId',
                         return_value='1234')
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = metering.MeteringRule(
            'rule', resource_defns['rule'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: resources.rule: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_metering_label_rule.assert_called_once_with({
            'metering_label_rule': {
                'metering_label_id': '1234',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False
            }
        })

    def test_delete(self):
        rsrc = self.create_metering_label_rule()
        self.mockclient.delete_metering_label_rule.return_value = None
        self.mockclient.show_metering_label_rule.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_metering_label_rule.assert_called_once_with({
            'metering_label_rule': {
                'metering_label_id': '1234',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False
            }
        })
        self.mockclient.delete_metering_label_rule.assert_called_once_with(
            '5678')
        self.mockclient.show_metering_label_rule.assert_called_once_with(
            '5678')

    def test_delete_already_gone(self):
        rsrc = self.create_metering_label_rule()
        self.mockclient.delete_metering_label_rule.side_effect = (
            exceptions.NeutronClientException(status_code=404))

        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

        self.mockclient.create_metering_label_rule.assert_called_once_with({
            'metering_label_rule': {
                'metering_label_id': '1234',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False
            }
        })
        self.mockclient.delete_metering_label_rule.assert_called_once_with(
            '5678')
        self.mockclient.show_metering_label_rule.assert_not_called()

    def test_delete_failed(self):
        rsrc = self.create_metering_label_rule()
        self.mockclient.delete_metering_label_rule.side_effect = (
            exceptions.NeutronClientException(status_code=400))

        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: resources.rule: '
            'An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)

        self.mockclient.create_metering_label_rule.assert_called_once_with({
            'metering_label_rule': {
                'metering_label_id': '1234',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False
            }
        })
        self.mockclient.delete_metering_label_rule.assert_called_once_with(
            '5678')
        self.mockclient.show_metering_label_rule.assert_not_called()

    def test_attribute(self):
        rsrc = self.create_metering_label_rule()
        self.mockclient.show_metering_label_rule.return_value = {
            'metering_label_rule': {
                'metering_label_id': '1234',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False
            }
        }

        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('10.0.3.0/24', rsrc.FnGetAtt('remote_ip_prefix'))
        self.assertEqual('ingress', rsrc.FnGetAtt('direction'))
        self.assertIs(False, rsrc.FnGetAtt('excluded'))

        self.mockclient.create_metering_label_rule.assert_called_once_with({
            'metering_label_rule': {
                'metering_label_id': '1234',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False
            }
        })
        self.mockclient.show_metering_label_rule.assert_called_with('5678')
