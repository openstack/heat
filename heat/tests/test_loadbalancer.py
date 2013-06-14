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


import mox
import re

from oslo.config import cfg
from heat.common import exception
from heat.common import config
from heat.common import template_format
from heat.engine import clients
from heat.engine import scheduler
from heat.engine.resources import instance
from heat.engine.resources import user
from heat.engine.resources import loadbalancer as lb
from heat.engine.resources import wait_condition as wc
from heat.engine.resource import Metadata
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack
from heat.tests.v1_1 import fakes
from heat.tests import fakes as test_fakes


lb_template = '''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "LB Template",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
   },
  "Resources": {
    "WikiServerOne": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId": "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
        "KeyName"        : "test",
        "UserData"       : "some data"
      }
    },
    "LoadBalancer" : {
      "Type" : "AWS::ElasticLoadBalancing::LoadBalancer",
      "Properties" : {
        "AvailabilityZones" : ["nova"],
        "Instances" : [{"Ref": "WikiServerOne"}],
        "Listeners" : [ {
          "LoadBalancerPort" : "80",
          "InstancePort" : "80",
          "Protocol" : "HTTP"
        }]
      }
    }
  }
}
'''


class LoadBalancerTest(HeatTestCase):
    def setUp(self):
        super(LoadBalancerTest, self).setUp()
        config.register_engine_opts()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.m.StubOutWithMock(Metadata, '__set__')
        self.fkc = test_fakes.FakeKeystoneClient(
            username='test_stack.CfnLBUser')

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://127.0.0.1:8000/v1/waitcondition')
        setup_dummy_db()

    def create_loadbalancer(self, t, stack, resource_name):
        rsrc = lb.LoadBalancer(resource_name,
                               t['Resources'][resource_name],
                               stack)
        self.assertEqual(None, rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_loadbalancer(self):
        self.m.StubOutWithMock(scheduler.TaskRunner, '_sleep')
        scheduler.TaskRunner._sleep(mox.IsA(int)).MultipleTimes()

        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().AndReturn(self.fkc)
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        user.AccessKey.keystone().AndReturn(self.fkc)

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
        wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(self.fkc)

        server_name = utils.PhysName(utils.PhysName('test_stack',
                                                    'LoadBalancer'),
                                     'LB_instance')
        clients.OpenStackClients.nova(
            "compute").MultipleTimes().AndReturn(self.fc)
        self.fc.servers.create(
            flavor=2, image=745, key_name='test',
            meta=None, nics=None, name=server_name,
            scheduler_hints=None, userdata=mox.IgnoreArg(),
            security_groups=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])
        Metadata.__set__(mox.IgnoreArg(),
                         mox.IgnoreArg()).AndReturn(None)

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'get_status')
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        self.m.ReplayAll()

        t = template_format.parse(lb_template)
        s = parse_stack(t)
        s.store()

        rsrc = self.create_loadbalancer(t, s, 'LoadBalancer')

        hc = {
            'Target': 'HTTP:80/',
            'HealthyThreshold': '3',
            'UnhealthyThreshold': '5',
            'Interval': '30',
            'Timeout': '5'}
        rsrc.t['Properties']['HealthCheck'] = hc
        self.assertEqual(None, rsrc.validate())

        hc['Timeout'] = 35
        self.assertEqual(
            {'Error': 'Interval must be larger than Timeout'},
            rsrc.validate())
        hc['Timeout'] = 5

        self.assertEqual('LoadBalancer', rsrc.FnGetRefId())

        templ = template_format.parse(lb.lb_template)
        ha_cfg = rsrc._haproxy_config(templ, rsrc.properties['Instances'])
        self.assertRegexpMatches(ha_cfg, 'bind \*:80')
        self.assertRegexpMatches(ha_cfg, 'server server1 1\.2\.3\.4:80 '
                                 'check inter 30s fall 5 rise 3')
        self.assertRegexpMatches(ha_cfg, 'timeout check 5s')

        id_list = []
        for inst_name in ['WikiServerOne1', 'WikiServerOne2']:
            inst = instance.Instance(inst_name,
                                     s.t['Resources']['WikiServerOne'],
                                     s)
            id_list.append(inst.FnGetRefId())

        rsrc.handle_update(rsrc.json_snippet, {}, {'Instances': id_list})

        self.assertEqual('4.5.6.7', rsrc.FnGetAtt('DNSName'))
        self.assertEqual('', rsrc.FnGetAtt('SourceSecurityGroupName'))

        try:
            rsrc.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual(None, rsrc.handle_update({}, {}, {}))

        self.m.VerifyAll()

    def assertRegexpMatches(self, text, expected_regexp, msg=None):
        """Fail the test unless the text matches the regular expression."""
        if isinstance(expected_regexp, basestring):
            expected_regexp = re.compile(expected_regexp)
        if not expected_regexp.search(text):
            msg = msg or "Regexp didn't match"
            msg = '%s: %r not found in %r' % (msg,
                                              expected_regexp.pattern, text)
            raise self.failureException(msg)
