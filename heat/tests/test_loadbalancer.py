
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

import re

import mock
import mox
from oslo.config import cfg

from heat.common import exception
from heat.common import template_format
from heat.engine import clients
from heat.engine.resource import Metadata
from heat.engine.resources import instance
from heat.engine.resources import loadbalancer as lb
from heat.engine.resources import wait_condition as wc
from heat.engine import scheduler
from heat.engine import stack_user
from heat.tests.common import HeatTestCase
from heat.tests import fakes as test_fakes
from heat.tests import utils
from heat.tests.v1_1 import fakes


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

lb_template_nokey = '''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "LB Template",
  "Resources": {
    "WikiServerOne": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId": "F17-x86_64-gold",
        "InstanceType"   : "m1.large",
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
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.m.StubOutWithMock(Metadata, '__set__')
        self.fkc = test_fakes.FakeKeystoneClient(
            username='test_stack.CfnLBUser')

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        utils.setup_dummy_db()

    def create_loadbalancer(self, t, stack, resource_name):
        rsrc = lb.LoadBalancer(resource_name,
                               t['Resources'][resource_name],
                               stack)
        self.assertIsNone(rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def _create_stubs(self, key_name='test', stub_meta=True):

        self.m.StubOutWithMock(stack_user.StackUser, 'keystone')
        stack_user.StackUser.keystone().MultipleTimes().AndReturn(self.fkc)

        server_name = utils.PhysName(
            utils.PhysName('test_stack', 'LoadBalancer'),
            'LB_instance',
            limit=instance.Instance.physical_resource_name_limit)
        clients.OpenStackClients.nova(
            "compute").MultipleTimes().AndReturn(self.fc)
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)
        self.fc.servers.create(
            flavor=2, image=746, key_name=key_name,
            meta=None, nics=None, name=server_name,
            scheduler_hints=None, userdata=mox.IgnoreArg(),
            security_groups=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])
        if stub_meta:
            Metadata.__set__(mox.IgnoreArg(),
                             mox.IgnoreArg()).AndReturn(None)

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'get_status')
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])

    def test_loadbalancer(self):
        self._create_stubs()

        self.m.ReplayAll()

        t = template_format.parse(lb_template)
        s = utils.parse_stack(t)
        s.store()

        rsrc = self.create_loadbalancer(t, s, 'LoadBalancer')

        hc = {
            'Target': 'HTTP:80/',
            'HealthyThreshold': '3',
            'UnhealthyThreshold': '5',
            'Interval': '30',
            'Timeout': '5'}
        rsrc.t['Properties']['HealthCheck'] = hc
        self.assertIsNone(rsrc.validate())

        hc['Timeout'] = 35
        self.assertEqual(
            {'Error': 'Interval must be larger than Timeout'},
            rsrc.validate())
        hc['Timeout'] = 5

        self.assertEqual('LoadBalancer', rsrc.FnGetRefId())

        templ = template_format.parse(lb.lb_template_default)
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
        self.assertEqual('', rsrc.FnGetAtt('SourceSecurityGroup.GroupName'))

        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'Foo')

        self.assertIsNone(rsrc.handle_update({}, {}, {}))

        self.m.VerifyAll()

    def test_loadbalancer_nokey(self):
        self._create_stubs(key_name=None, stub_meta=False)
        self.m.ReplayAll()

        t = template_format.parse(lb_template_nokey)
        s = utils.parse_stack(t)
        s.store()

        rsrc = self.create_loadbalancer(t, s, 'LoadBalancer')
        self.assertEqual('LoadBalancer', rsrc.name)
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

    def test_loadbalancer_validate_badtemplate(self):
        cfg.CONF.set_override('loadbalancer_template', '/a/noexist/x.y')

        t = template_format.parse(lb_template)
        s = utils.parse_stack(t)
        s.store()

        rsrc = lb.LoadBalancer('LoadBalancer',
                               t['Resources']['LoadBalancer'],
                               s)
        self.assertRaises(exception.StackValidationFailed, rsrc.validate)

    def setup_loadbalancer(self, include_keyname=True):
        template = template_format.parse(lb_template)
        if not include_keyname:
            del template['Parameters']['KeyName']
        stack = utils.parse_stack(template)

        resource_name = 'LoadBalancer'
        lb_json = template['Resources'][resource_name]
        return lb.LoadBalancer(resource_name, lb_json, stack)

    def test_child_params_without_key_name(self):
        rsrc = self.setup_loadbalancer(False)
        self.assertEqual({}, rsrc.child_params())

    def test_child_params_with_key_name(self):
        rsrc = self.setup_loadbalancer()
        params = rsrc.child_params()
        self.assertEqual('test', params['KeyName'])

    def test_child_template_without_key_name(self):
        rsrc = self.setup_loadbalancer(False)
        parsed_template = {
            'Resources': {'LB_instance': {'Properties': {'KeyName': 'foo'}}},
            'Parameters': {'KeyName': 'foo'}
        }
        rsrc.get_parsed_template = mock.Mock(return_value=parsed_template)

        tmpl = rsrc.child_template()
        self.assertNotIn('KeyName', tmpl['Parameters'])
        self.assertNotIn('KeyName',
                         tmpl['Resources']['LB_instance']['Properties'])

    def test_child_template_with_key_name(self):
        rsrc = self.setup_loadbalancer()
        rsrc.get_parsed_template = mock.Mock(return_value='foo')

        self.assertEqual('foo', rsrc.child_template())
