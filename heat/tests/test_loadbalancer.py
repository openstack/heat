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


import re
import os

import unittest
import mox

from nose.plugins.attrib import attr

from oslo.config import cfg
from heat.common import exception
from heat.common import context
from heat.common import template_format
from heat.engine import parser
from heat.engine.resources import instance
from heat.engine.resources import user
from heat.engine.resources import loadbalancer as lb
from heat.engine.resources import wait_condition as wc
from heat.engine.resource import Metadata
from heat.tests.v1_1 import fakes
from heat.tests import fakes as test_fakes


def create_context(mocks, user='lb_test_user',
                   tenant='test_tenant', ctx=None):
    ctx = ctx or context.get_admin_context()
    mocks.StubOutWithMock(ctx, 'username')
    mocks.StubOutWithMock(ctx, 'tenant_id')
    ctx.username = user
    ctx.tenant_id = tenant
    return ctx


@attr(tag=['unit', 'resource'])
@attr(speed='fast')
class LoadBalancerTest(unittest.TestCase):
    def setUp(self):
        self.m = mox.Mox()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(lb.LoadBalancer, 'nova')
        self.m.StubOutWithMock(instance.Instance, 'nova')
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.m.StubOutWithMock(Metadata, '__set__')
        self.fkc = test_fakes.FakeKeystoneClient(
            username='test_stack.CfnLBUser')

        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://127.0.0.1:8000/v1/waitcondition')

    def tearDown(self):
        self.m.UnsetStubs()
        print "LoadBalancerTest teardown complete"

    def load_template(self):
        self.path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')
        f = open("%s/WordPress_With_LB.template" % self.path)
        t = template_format.parse(f.read())
        f.close()
        return t

    def parse_stack(self, t):
        template = parser.Template(t)
        params = parser.Parameters('test_stack', template, {'KeyName': 'test'})
        stack = parser.Stack(create_context(self.m), 'test_stack', template,
                             params, stack_id=None, disable_rollback=True)
        stack.store()

        return stack

    def create_loadbalancer(self, t, stack, resource_name):
        resource = lb.LoadBalancer(resource_name,
                                   t['Resources'][resource_name],
                                   stack)
        self.assertEqual(None, resource.validate())
        self.assertEqual(None, resource.create())
        self.assertEqual(lb.LoadBalancer.CREATE_COMPLETE, resource.state)
        return resource

    def test_loadbalancer(self):
        self.m.StubOutWithMock(user.User, 'keystone')
        user.User.keystone().MultipleTimes().AndReturn(self.fkc)
        self.m.StubOutWithMock(user.AccessKey, 'keystone')
        user.AccessKey.keystone().MultipleTimes().AndReturn(self.fkc)

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'keystone')
        wc.WaitConditionHandle.keystone().MultipleTimes().AndReturn(self.fkc)

        lb.LoadBalancer.nova().AndReturn(self.fc)
        instance.Instance.nova().MultipleTimes().AndReturn(self.fc)
        self.fc.servers.create(
            flavor=2, image=745, key_name='test',
            meta=None, nics=None, name=u'test_stack.LoadBalancer.LB_instance',
            scheduler_hints=None, userdata=mox.IgnoreArg(),
            security_groups=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])
        Metadata.__set__(mox.IgnoreArg(),
                         mox.IgnoreArg()).MultipleTimes().AndReturn(None)

        lb.LoadBalancer.nova().MultipleTimes().AndReturn(self.fc)

        self.m.StubOutWithMock(wc.WaitConditionHandle, 'get_status')
        wc.WaitConditionHandle.get_status().AndReturn(['SUCCESS'])
        self.m.ReplayAll()

        t = self.load_template()
        s = self.parse_stack(t)

        resource = self.create_loadbalancer(t, s, 'LoadBalancer')

        hc = {
            'Target': 'HTTP:80/',
            'HealthyThreshold': '3',
            'UnhealthyThreshold': '5',
            'Interval': '30',
            'Timeout': '5'}
        resource.t['Properties']['HealthCheck'] = hc
        self.assertEqual(None, resource.validate())

        hc['Timeout'] = 35
        self.assertEqual(
            {'Error': 'Interval must be larger than Timeout'},
            resource.validate())
        hc['Timeout'] = 5

        self.assertEqual('LoadBalancer', resource.FnGetRefId())

        templ = template_format.parse(lb.lb_template)
        ha_cfg = resource._haproxy_config(templ,
                                          resource.properties['Instances'])
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

        resource.reload(id_list)

        self.assertEqual('4.5.6.7', resource.FnGetAtt('DNSName'))
        self.assertEqual('', resource.FnGetAtt('SourceSecurityGroupName'))

        try:
            resource.FnGetAtt('Foo')
            raise Exception('Expected InvalidTemplateAttribute')
        except exception.InvalidTemplateAttribute:
            pass

        self.assertEqual(lb.LoadBalancer.UPDATE_REPLACE,
                         resource.handle_update({}))

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
