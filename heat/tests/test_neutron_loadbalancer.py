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

import copy

from testtools import skipIf

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine import scheduler
from heat.engine.resources.neutron import loadbalancer
from heat.openstack.common.importutils import try_import
from heat.tests import fakes
from heat.tests import utils
from heat.tests.common import HeatTestCase

neutronclient = try_import('neutronclient.v2_0.client')

health_monitor_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Template to test load balancer resources",
  "Parameters" : {},
  "Resources" : {
    "monitor": {
      "Type": "OS::Neutron::HealthMonitor",
      "Properties": {
        "type": "HTTP",
        "delay": 3,
        "max_retries": 5,
        "timeout": 10
      }
    }
  }
}
'''


@skipIf(neutronclient is None, 'neutronclient unavailable')
class HealthMonitorTest(HeatTestCase):

    def setUp(self):
        super(HealthMonitorTest, self).setUp()
        self.m.StubOutWithMock(neutronclient.Client, 'create_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'delete_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'show_health_monitor')
        self.m.StubOutWithMock(neutronclient.Client, 'update_health_monitor')
        self.m.StubOutWithMock(clients.OpenStackClients, 'keystone')
        utils.setup_dummy_db()

    def create_health_monitor(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_health_monitor({
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}
        ).AndReturn({'health_monitor': {'id': '5678'}})

        snippet = template_format.parse(health_monitor_template)
        stack = utils.parse_stack(snippet)
        return loadbalancer.HealthMonitor(
            'monitor', snippet['Resources']['monitor'], stack)

    def test_create(self):
        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_failed(self):
        clients.OpenStackClients.keystone().AndReturn(
            fakes.FakeKeystoneClient())
        neutronclient.Client.create_health_monitor({
            'health_monitor': {
                'delay': 3, 'max_retries': 5, 'type': u'HTTP',
                'timeout': 10, 'admin_state_up': True}}
        ).AndRaise(loadbalancer.NeutronClientException())
        self.m.ReplayAll()

        snippet = template_format.parse(health_monitor_template)
        stack = utils.parse_stack(snippet)
        rsrc = loadbalancer.HealthMonitor(
            'monitor', snippet['Resources']['monitor'], stack)
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        neutronclient.Client.delete_health_monitor('5678').AndReturn(None)
        neutronclient.Client.show_health_monitor('5678').AndRaise(
            loadbalancer.NeutronClientException(status_code=404))

        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_already_gone(self):
        neutronclient.Client.delete_health_monitor('5678').AndRaise(
            loadbalancer.NeutronClientException(status_code=404))

        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_failed(self):
        neutronclient.Client.delete_health_monitor('5678').AndRaise(
            loadbalancer.NeutronClientException(status_code=400))

        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.delete))
        self.assertEqual((rsrc.DELETE, rsrc.FAILED), rsrc.state)
        self.m.VerifyAll()

    def test_attribute(self):
        rsrc = self.create_health_monitor()
        neutronclient.Client.show_health_monitor('5678').MultipleTimes(
        ).AndReturn(
            {'health_monitor': {'admin_state_up': True, 'delay': 3}})
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual(True, rsrc.FnGetAtt('admin_state_up'))
        self.assertEqual(3, rsrc.FnGetAtt('delay'))
        self.m.VerifyAll()

    def test_attribute_failed(self):
        rsrc = self.create_health_monitor()
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'subnet_id')
        self.m.VerifyAll()

    def test_update(self):
        rsrc = self.create_health_monitor()
        neutronclient.Client.update_health_monitor(
            '5678', {'health_monitor': {'delay': 10}}).AndReturn(None)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['delay'] = 10
        self.assertEqual(None, rsrc.update(update_template))

        self.m.VerifyAll()
