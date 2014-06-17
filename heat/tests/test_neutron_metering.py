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

from neutronclient.common import exceptions
from neutronclient.v2_0 import client as neutronclient
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.neutron import metering
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils


metering_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test metering resources",
  "Parameters" : {},
  "Resources" : {
    "label": {
      "Type": "OS::Neutron::MeteringLabel",
      "Properties": {
        "name": "TestLabel",
        "description": "Description of TestLabel"
       }
    },
    "rule": {
      "Type": "OS::Neutron::MeteringRule",
      "Properties": {
        "metering_label_id": { "Ref" : "label" },
        "remote_ip_prefix": "10.0.3.0/24",
        "direction": "ingress",
        "excluded": false
      }
    }
  }
}
'''


class MeteringLabelTest(HeatTestCase):

    def setUp(self):
        super(MeteringLabelTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_metering_label')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_metering_label')
        self.m.StubOutWithMock(neutronclient.Client, 'show_metering_label')
        self.m.StubOutWithMock(neutronclient.Client,
                               'create_metering_label_rule')
        self.m.StubOutWithMock(neutronclient.Client,
                               'delete_metering_label_rule')
        self.m.StubOutWithMock(neutronclient.Client,
                               'show_metering_label_rule')
        self.stub_keystoneclient()

    def create_metering_label(self):
        neutronclient.Client.create_metering_label({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel'}
        }).AndReturn({'metering_label': {'id': '1234'}})

        snippet = template_format.parse(metering_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return metering.MeteringLabel(
            'label', resource_defns['label'], stack)

    def test_create(self):
        rsrc = self.create_metering_label()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        neutronclient.Client.create_metering_label({
            'metering_label': {
                'name': 'TestLabel',
                'description': 'Description of TestLabel'}
        }).AndRaise(exceptions.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(metering_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = metering.MeteringLabel(
            'label', resource_defns['label'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_metering_label('1234')
        neutronclient.Client.show_metering_label('1234').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_metering_label()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_metering_label('1234').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_metering_label()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_metering_label('1234').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_metering_label()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_metering_label()
        neutronclient.Client.show_metering_label('1234').MultipleTimes(
        ).AndReturn(
            {'metering_label':
                {'name': 'TestLabel',
                 'description': 'Description of TestLabel'}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('TestLabel', rsrc.FnGetAtt('name'))
        self.assertEqual('Description of TestLabel',
                         rsrc.FnGetAtt('description'))
        self.m.VerifyAll()


class MeteringRuleTest(HeatTestCase):

    def setUp(self):
        super(MeteringRuleTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_metering_label')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_metering_label')
        self.m.StubOutWithMock(neutronclient.Client, 'show_metering_label')
        self.m.StubOutWithMock(neutronclient.Client,
                               'create_metering_label_rule')
        self.m.StubOutWithMock(neutronclient.Client,
                               'delete_metering_label_rule')
        self.m.StubOutWithMock(neutronclient.Client,
                               'show_metering_label_rule')
        self.stub_keystoneclient()

    def create_metering_label_rule(self):
        neutronclient.Client.create_metering_label_rule({
            'metering_label_rule': {
                'metering_label_id': 'None',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False}
        }).AndReturn({'metering_label_rule': {'id': '5678'}})

        snippet = template_format.parse(metering_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        return metering.MeteringRule(
            'rule', resource_defns['rule'], stack)

    def test_create(self):
        rsrc = self.create_metering_label_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        neutronclient.Client.create_metering_label_rule({
            'metering_label_rule': {
                'metering_label_id': 'None',
                'remote_ip_prefix': '10.0.3.0/24',
                'direction': 'ingress',
                'excluded': False}
        }).AndRaise(exceptions.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(metering_template)
        stack = utils.parse_stack(snippet)
        resource_defns = stack.t.resource_definitions(stack)
        rsrc = metering.MeteringRule(
            'rule', resource_defns['rule'], stack)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.create))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_metering_label_rule('5678')
        neutronclient.Client.show_metering_label_rule('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_metering_label_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_metering_label_rule('5678').AndRaise(
            exceptions.NeutronClientException(status_code=404))

        rsrc = self.create_metering_label_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_metering_label_rule('5678').AndRaise(
            exceptions.NeutronClientException(status_code=400))

        rsrc = self.create_metering_label_rule()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(rsrc.delete))
        self.assertEqual(
            'NeutronClientException: An unknown exception occurred.',
            six.text_type(error))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_metering_label_rule()
        neutronclient.Client.show_metering_label_rule('5678').MultipleTimes(
        ).AndReturn(
            {'metering_label_rule':
                {'metering_label_id': 'None',
                 'remote_ip_prefix': '10.0.3.0/24',
                 'direction': 'ingress',
                 'excluded': False}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual('10.0.3.0/24', rsrc.FnGetAtt('remote_ip_prefix'))
        self.assertEqual('ingress', rsrc.FnGetAtt('direction'))
        self.assertIs(False, rsrc.FnGetAtt('excluded'))
        self.m.VerifyAll()
