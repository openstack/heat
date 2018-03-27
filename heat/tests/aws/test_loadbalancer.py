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

import copy

import mock
from oslo_config import cfg

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import nova
from heat.engine import node_data
from heat.engine.resources.aws.lb import loadbalancer as lb
from heat.engine import rsrc_defn
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils


lb_template = '''
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "LB Template",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    },
    "LbFlavor" : {
      "Description" : "Flavor to use for LoadBalancer instance",
      "Type": "String",
      "Default": "m1.heat"
    },
    "LbImageId" : {
      "Description" : "Image to use",
      "Type" : "String",
      "Default" : "image123"
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
        "SecurityGroups": ["sg_1"],
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


class LoadBalancerTest(common.HeatTestCase):
    def setUp(self):
        super(LoadBalancerTest, self).setUp()
        self.fc = fakes_nova.FakeClient()

    def test_loadbalancer(self):
        t = template_format.parse(lb_template)
        s = utils.parse_stack(t)
        s.store()
        resource_name = 'LoadBalancer'
        lb_defn = s.t.resource_definitions(s)[resource_name]
        rsrc = lb.LoadBalancer(resource_name, lb_defn, s)

        self.patchobject(nova.NovaClientPlugin, 'client',
                         return_value=self.fc)
        initial_md = {'AWS::CloudFormation::Init':
                      {'config':
                       {'files':
                        {'/etc/haproxy/haproxy.cfg': {'content': 'initial'}}}}}
        ha_cfg = '\n'.join(['\nglobal', '    daemon', '    maxconn 256',
                            '    stats socket /tmp/.haproxy-stats',
                            '\ndefaults',
                            '    mode http\n    timeout connect 5000ms',
                            '    timeout client 50000ms',
                            '    timeout server 50000ms\n\nfrontend http',
                            '    bind *:80\n    default_backend servers',
                            '\nbackend servers\n    balance roundrobin',
                            '    option http-server-close',
                            '    option forwardfor\n    option httpchk',
                            '\n    server server1 1.2.3.4:80',
                            '    server server2 0.0.0.0:80\n'])
        expected_md = {'AWS::CloudFormation::Init':
                       {'config':
                        {'files':
                         {'/etc/haproxy/haproxy.cfg': {
                             'content': ha_cfg}}}}}

        md = mock.Mock()
        md.metadata_get.return_value = copy.deepcopy(initial_md)
        rsrc.nested = mock.Mock(return_value={'LB_instance': md})

        prop_diff = {'Instances': ['WikiServerOne1', 'WikiServerOne2']}
        props = copy.copy(rsrc.properties.data)
        props.update(prop_diff)
        update_defn = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                   props)
        rsrc.handle_update(update_defn, {}, prop_diff)
        self.assertIsNone(rsrc.handle_update(rsrc.t, {}, {}))
        md.metadata_get.assert_called_once_with()
        md.metadata_set.assert_called_once_with(expected_md)

    def test_loadbalancer_validate_hchk_good(self):
        hc = {
            'Target': 'HTTP:80/',
            'HealthyThreshold': '3',
            'UnhealthyThreshold': '5',
            'Interval': '30',
            'Timeout': '5'}
        rsrc = self.setup_loadbalancer(hc=hc)
        rsrc._parse_nested_stack = mock.Mock()
        self.assertIsNone(rsrc.validate())

    def test_loadbalancer_validate_hchk_int_gt_tmo(self):
        hc = {
            'Target': 'HTTP:80/',
            'HealthyThreshold': '3',
            'UnhealthyThreshold': '5',
            'Interval': '30',
            'Timeout': '35'}
        rsrc = self.setup_loadbalancer(hc=hc)
        rsrc._parse_nested_stack = mock.Mock()
        self.assertEqual(
            {'Error': 'Interval must be larger than Timeout'},
            rsrc.validate())

    def test_loadbalancer_validate_badtemplate(self):
        cfg.CONF.set_override('loadbalancer_template', '/a/noexist/x.y')
        rsrc = self.setup_loadbalancer()
        self.assertRaises(exception.StackValidationFailed, rsrc.validate)

    def setup_loadbalancer(self, include_magic=True, cache_data=None, hc=None):
        template = template_format.parse(lb_template)
        if not include_magic:
            del template['Parameters']['KeyName']
            del template['Parameters']['LbFlavor']
            del template['Parameters']['LbImageId']
        if hc is not None:
            props = template['Resources']['LoadBalancer']['Properties']
            props['HealthCheck'] = hc
        self.stack = utils.parse_stack(template, cache_data=cache_data)

        resource_name = 'LoadBalancer'
        lb_defn = self.stack.defn.resource_definition(resource_name)
        return lb.LoadBalancer(resource_name, lb_defn, self.stack)

    def test_loadbalancer_refid(self):
        rsrc = self.setup_loadbalancer()
        self.assertEqual('LoadBalancer', rsrc.FnGetRefId())

    def test_loadbalancer_refid_convergence_cache_data(self):
        cache_data = {'LoadBalancer': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'LoadBalancer_convg_mock'
        })}
        rsrc = self.setup_loadbalancer(cache_data=cache_data)
        self.assertEqual('LoadBalancer_convg_mock',
                         self.stack.defn[rsrc.name].FnGetRefId())

    def test_loadbalancer_attr_dnsname(self):
        rsrc = self.setup_loadbalancer()
        rsrc.get_output = mock.Mock(return_value='1.3.5.7')
        self.assertEqual('1.3.5.7', rsrc.FnGetAtt('DNSName'))
        rsrc.get_output.assert_called_once_with('PublicIp')

    def test_loadbalancer_attr_not_supported(self):
        rsrc = self.setup_loadbalancer()
        for attr in ['CanonicalHostedZoneName',
                     'CanonicalHostedZoneNameID',
                     'SourceSecurityGroup.GroupName',
                     'SourceSecurityGroup.OwnerAlias']:
            self.assertEqual('', rsrc.FnGetAtt(attr))

    def test_loadbalancer_attr_invalid(self):
        rsrc = self.setup_loadbalancer()
        self.assertRaises(exception.InvalidTemplateAttribute,
                          rsrc.FnGetAtt, 'Foo')

    def test_child_params_without_key_name(self):
        rsrc = self.setup_loadbalancer(False)
        self.assertNotIn('KeyName', rsrc.child_params())

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

    def test_child_params_with_flavor(self):
        rsrc = self.setup_loadbalancer()
        params = rsrc.child_params()
        self.assertEqual('m1.heat', params['LbFlavor'])

    def test_child_params_without_flavor(self):
        rsrc = self.setup_loadbalancer(False)
        params = rsrc.child_params()
        self.assertNotIn('LbFlavor', params)

    def test_child_params_with_image_id(self):
        rsrc = self.setup_loadbalancer()
        params = rsrc.child_params()
        self.assertEqual('image123', params['LbImageId'])

    def test_child_params_without_image_id(self):
        rsrc = self.setup_loadbalancer(False)
        params = rsrc.child_params()
        self.assertNotIn('LbImageId', params)

    def test_child_params_with_sec_gr(self):
        rsrc = self.setup_loadbalancer(False)
        params = rsrc.child_params()
        expected = {'SecurityGroups': ['sg_1']}
        self.assertEqual(expected, params)

    def test_child_params_default_sec_gr(self):
        template = template_format.parse(lb_template)
        del template['Parameters']['KeyName']
        del template['Parameters']['LbFlavor']
        del template['Resources']['LoadBalancer']['Properties'][
            'SecurityGroups']
        del template['Parameters']['LbImageId']
        stack = utils.parse_stack(template)

        resource_name = 'LoadBalancer'
        lb_defn = stack.t.resource_definitions(stack)[resource_name]
        rsrc = lb.LoadBalancer(resource_name, lb_defn, stack)
        params = rsrc.child_params()
        # None value means, that will be used default [] for parameter
        expected = {'SecurityGroups': None}
        self.assertEqual(expected, params)


class HaProxyConfigTest(common.HeatTestCase):
    def setUp(self):
        super(HaProxyConfigTest, self).setUp()
        self.stack = utils.parse_stack(template_format.parse(lb_template))
        resource_name = 'LoadBalancer'
        lb_defn = self.stack.t.resource_definitions(self.stack)[resource_name]
        self.lb = lb.LoadBalancer(resource_name, lb_defn, self.stack)
        self.lb.client_plugin = mock.Mock()

    def _mock_props(self, props):
        def get_props(name):
            return props[name]

        self.lb.properties = mock.MagicMock()
        self.lb.properties.__getitem__.side_effect = get_props

    def test_combined(self):
        self.lb._haproxy_config_global = mock.Mock(return_value='one,')
        self.lb._haproxy_config_frontend = mock.Mock(return_value='two,')
        self.lb._haproxy_config_backend = mock.Mock(return_value='three,')
        self.lb._haproxy_config_servers = mock.Mock(return_value='four')
        actual = self.lb._haproxy_config([3, 5])
        self.assertEqual('one,two,three,four\n', actual)

        self.lb._haproxy_config_global.assert_called_once_with()
        self.lb._haproxy_config_frontend.assert_called_once_with()
        self.lb._haproxy_config_backend.assert_called_once_with()
        self.lb._haproxy_config_servers.assert_called_once_with([3, 5])

    def test_global(self):
        exp = '''
global
    daemon
    maxconn 256
    stats socket /tmp/.haproxy-stats

defaults
    mode http
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms
'''
        actual = self.lb._haproxy_config_global()
        self.assertEqual(exp, actual)

    def test_frontend(self):
        props = {'HealthCheck': {},
                 'Listeners': [{'LoadBalancerPort': 4014}]}
        self._mock_props(props)

        exp = '''
frontend http
    bind *:4014
    default_backend servers
'''
        actual = self.lb._haproxy_config_frontend()
        self.assertEqual(exp, actual)

    def test_backend_with_timeout(self):
        props = {'HealthCheck': {'Timeout': 43}}
        self._mock_props(props)

        actual = self.lb._haproxy_config_backend()
        exp = '''
backend servers
    balance roundrobin
    option http-server-close
    option forwardfor
    option httpchk
    timeout check 43s
'''
        self.assertEqual(exp, actual)

    def test_backend_no_timeout(self):
        self._mock_props({'HealthCheck': None})
        be = self.lb._haproxy_config_backend()

        exp = '''
backend servers
    balance roundrobin
    option http-server-close
    option forwardfor
    option httpchk

'''
        self.assertEqual(exp, be)

    def test_servers_none(self):
        props = {'HealthCheck': {},
                 'Listeners': [{'InstancePort': 1234}]}
        self._mock_props(props)
        actual = self.lb._haproxy_config_servers([])
        exp = ''
        self.assertEqual(exp, actual)

    def test_servers_no_check(self):
        props = {'HealthCheck': {},
                 'Listeners': [{'InstancePort': 4511}]}
        self._mock_props(props)

        def fake_to_ipaddr(inst):
            return '192.168.1.%s' % inst

        to_ip = self.lb.client_plugin.return_value.server_to_ipaddress
        to_ip.side_effect = fake_to_ipaddr

        actual = self.lb._haproxy_config_servers(range(1, 3))
        exp = '''
    server server1 192.168.1.1:4511
    server server2 192.168.1.2:4511'''
        self.assertEqual(exp.replace('\n', '', 1), actual)

    def test_servers_servers_and_check(self):
        props = {'HealthCheck': {'HealthyThreshold': 1,
                                 'Interval': 2,
                                 'Target': 'HTTP:80/',
                                 'Timeout': 45,
                                 'UnhealthyThreshold': 5
                                 },
                 'Listeners': [{'InstancePort': 1234}]}
        self._mock_props(props)

        def fake_to_ipaddr(inst):
            return '192.168.1.%s' % inst

        to_ip = self.lb.client_plugin.return_value.server_to_ipaddress
        to_ip.side_effect = fake_to_ipaddr

        actual = self.lb._haproxy_config_servers(range(1, 3))
        exp = '''
    server server1 192.168.1.1:1234 check inter 2s fall 5 rise 1
    server server2 192.168.1.2:1234 check inter 2s fall 5 rise 1'''
        self.assertEqual(exp.replace('\n', '', 1), actual)
