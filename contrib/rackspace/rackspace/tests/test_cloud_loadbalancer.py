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
import json
import mock
import six
import uuid

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

from ..resources import cloud_loadbalancer as lb  # noqa

# The following fakes are for pyrax


cert = """\
-----BEGIN CERTIFICATE-----
MIIFBjCCAu4CCQDWdcR5LY/+/jANBgkqhkiG9w0BAQUFADBFMQswCQYDVQQGEwJB
VTETMBEGA1UECAwKU29tZS1TdGF0ZTEhMB8GA1UECgwYSW50ZXJuZXQgV2lkZ2l0
cyBQdHkgTHRkMB4XDTE0MTAxNjE3MDYxNVoXDTE1MTAxNjE3MDYxNVowRTELMAkG
A1UEBhMCQVUxEzARBgNVBAgMClNvbWUtU3RhdGUxITAfBgNVBAoMGEludGVybmV0
IFdpZGdpdHMgUHR5IEx0ZDCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIB
AMm5NcP0tMKHblT6Ud1k8TxZ9/8uOHwUNPbvFsvSyCupj0J0vGCTjbuC2I5T/CXR
tnLEIt/EarlNAqcjbDCWtSyEKs3zDmmkreoIDEa8pyAQ2ycsCXGMxDN97F3/wlLZ
agUNM0FwGHLZWBg62bM6l+bpTUcX0PqSyv/aVMhJ8EPDX0Dx1RYsVwUzIe/HWC7x
vCmtDApAp1Fwq7AwlRaKU17sGwPWJ8+I8PyouBdqNuslHm7LQ0XvBA5DfkQA6feB
ZeJIyOtctM9WFWQI5fKOsyt5P306B3Zztw9VZLAmZ8qHex+R1WY1zXxDAwKEQz/X
8bRqMA/VU8OxJcK0AmY/1v/TFmAlRh2XBCIc+5UGtCcftWvZJAsKur8Hg5pPluGv
ptyqSgSsSKtOVWkyTANP1LyOkpBA8Kmkeo2CKXu1SCFypY5Q6E+Fy8Y8RaHJPvzR
NHcm1tkBvHOKyRso6FjvxuJEyIC9EyUK010nwQm7Qui11VgCSHBoaKVvkIbFfQdK
aCes0oQO5dqY0+fC/IFDhrxlvSd2Wk7KjuNjNu9kVN9Ama2pRTxhYKaN+GsHfoL7
ra6G9HjbUVULAdjCko3zOKEUzFLLf1VZYk7hDhyv9kovk0b8sr5WowxW7+9Wy0NK
WL5f2QgVCcoHw9bGhyuYQCdBfztNmKOWe9pGj6bQAx4pAgMBAAEwDQYJKoZIhvcN
AQEFBQADggIBALFSj3G2TEL/UWtNcPeY2fbxSGBrboFx3ur8+zTkdZzvfC8H9/UK
w0aRH0rK4+lKYDqF6A9bUHP17DaJm1lF9In38VVMOuur0ehUIn1S2U3OvlDLN68S
p5D4wGKMcUfUQ6pzhSKJCMvGX561TKHCc5fZhPruy75Xq2DcwJENE189foKLFvJs
ca4sIARqP6v1vfARcfH5leSsdIq8hy6VfL0BRATXfNHZh4SNbyDJYYTxrEUPHYXW
pzW6TziZXYNMG2ZRdHF/mDJuFzw2EklOrPC9MySCZv2i9swnqyuwNYh/SAMhodTv
ZDGy4nbjWNe5BflTMBceh45VpyTcnQulFhZQFwP79fK10BoDrOc1mEefhIqT+fPI
LJepLOf7CSXtYBcWbmMCLHNh+PrlCiA1QMTyd/AC1vvoiyCbs3M419XbXcBSDEh8
tACplmhf6z1vDkElWiDr8y0kujJ/Gie24iLTun6oHG+f+o6bbQ9w196T0olLcGx0
oAYL0Olqli6cWHhraVAzZ5t5PH4X9TiESuQ+PMjqGImCIUscXY4objdnB5dfPHoz
eF5whPl36/GK8HUixCibkCyqEOBBuNqhOz7nVLM0eg5L+TE5coizEBagxVCovYSj
fQ9zkIgaC5oeH6L0C1FFG1vRNSWokheBk14ztVoJCJyFr6p0/6pD7SeR
-----END CERTIFICATE-----"""

private_key = """\
-----BEGIN PRIVATE KEY-----
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
LpTt0Xs1OFZxaNpolW5Qis4os7UmmIRV
-----END PRIVATE KEY-----"""


class FakeClient(object):
    user_agent = "Fake"
    USER_AGENT = "Fake"


class FakeManager(object):
    api = FakeClient()

    def list(self):
        pass

    def get(self, item):
        pass

    def delete(self, item):
        pass

    def create(self, *args, **kwargs):
        pass

    def find(self, *args, **kwargs):
        pass

    def action(self, item, action_type, body=None):
        pass


class FakeLoadBalancerManager(object):
    def __init__(self, api=None, *args, **kwargs):
        pass

    def set_content_caching(self, *args, **kwargs):
        pass


class FakeNode(object):
    def __init__(self, address=None, port=None, condition=None, weight=None,
                 status=None, parent=None, type=None, id=None):
        if not (address and port):
            # This mimics the check that pyrax does on Node instantiation
            raise TypeError("You must include an address and "
                            "a port when creating a node.")
        self.address = address
        self.port = port
        self.condition = condition
        self.weight = weight
        self.status = status
        self.parent = parent
        self.type = type
        self.id = id

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)


class FakeVirtualIP(object):
    def __init__(self, address=None, port=None, condition=None,
                 ipVersion=None, type=None):
        self.address = address
        self.port = port
        self.condition = condition
        self.ipVersion = ipVersion
        self.type = type

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)


class FakeLoadBalancerClient(object):
    def __init__(self, *args, **kwargs):
        self.Node = FakeNode
        self.VirtualIP = FakeVirtualIP
        pass

    def get(self, *args, **kwargs):
        pass

    def create(self, *args, **kwargs):
        pass


class FakeLoadBalancer(object):
    def __init__(self, name=None, info=None, *args, **kwargs):
        name = name or uuid.uuid4()
        info = info or {"fake": "fake"}
        self.id = uuid.uuid4()
        self.manager = FakeLoadBalancerManager()
        self.Node = FakeNode
        self.VirtualIP = FakeVirtualIP
        self.nodes = []

    def get(self, *args, **kwargs):
        pass

    def add_nodes(self, *args, **kwargs):
        pass

    def add_ssl_termination(self, *args, **kwargs):
        pass

    def set_error_page(self, *args, **kwargs):
        pass

    def clear_error_page(self, *args, **kwargs):
        pass

    def add_access_list(self, *args, **kwargs):
        pass

    def update(self, *args, **kwargs):
        pass

    def add_health_monitor(self, *args, **kwargs):
        pass

    def delete_health_monitor(self, *args, **kwargs):
        pass

    def delete_ssl_termination(self, *args, **kwargs):
        pass

    def set_metadata(self, *args, **kwargs):
        pass

    def delete_metadata(self, *args, **kwargs):
        pass

    def add_connection_throttle(self, *args, **kwargs):
        pass

    def delete_connection_throttle(self, *args, **kwargs):
        pass


class LoadBalancerWithFakeClient(lb.CloudLoadBalancer):
    def cloud_lb(self):
        return FakeLoadBalancerClient()


def override_resource():
    return {
        'Rackspace::Cloud::LoadBalancer': LoadBalancerWithFakeClient
    }


class LoadBalancerTest(common.HeatTestCase):

    def setUp(self):
        super(LoadBalancerTest, self).setUp()

        self.lb_template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": "fawef",
            "Resources": {
                self._get_lb_resource_name(): {
                    "Type": "Rackspace::Cloud::LoadBalancer",
                    "Properties": {
                        "name": "test-clb",
                        "nodes": [{"addresses": ["166.78.103.141"],
                                   "port": 80,
                                   "condition": "ENABLED"}],
                        "protocol": "HTTP",
                        "port": 80,
                        "virtualIps": [
                            {"type": "PUBLIC", "ipVersion": "IPV6"}],
                        "algorithm": 'LEAST_CONNECTIONS',
                        "connectionThrottle": {'maxConnectionRate': 1000},
                        'timeout': 110,
                        'contentCaching': 'DISABLED'
                    }
                }
            }
        }

        self.lb_name = 'test-clb'
        self.expected_body = {
            "nodes": [FakeNode(address=u"166.78.103.141", port=80,
                               condition=u"ENABLED")],
            "protocol": u'HTTP',
            "port": 80,
            "virtual_ips": [FakeVirtualIP(type=u"PUBLIC", ipVersion=u"IPV6")],
            "halfClosed": None,
            "algorithm": u'LEAST_CONNECTIONS',
            "connectionThrottle": {'maxConnectionRate': 1000,
                                   'maxConnections': None,
                                   'rateInterval': None,
                                   'minConnections': None},
            "connectionLogging": None,
            "halfClosed": None,
            "healthMonitor": None,
            "metadata": None,
            "sessionPersistence": None,
            "timeout": 110
        }

        lb.resource_mapping = override_resource
        resource._register_class("Rackspace::Cloud::LoadBalancer",
                                 LoadBalancerWithFakeClient)

    def _get_lb_resource_name(self):
        return "lb-" + str(uuid.uuid4())

    def __getattribute__(self, name):
        if name == 'expected_body' or name == 'lb_template':
            return copy.deepcopy(super(LoadBalancerTest, self)
                                 .__getattribute__(name))
        return super(LoadBalancerTest, self).__getattribute__(name)

    def _mock_create(self, tmpl, stack, resource_name, lb_name, lb_body):
        resource_defns = tmpl.resource_definitions(stack)
        rsrc = LoadBalancerWithFakeClient(resource_name,
                                          resource_defns[resource_name],
                                          stack)
        self.m.StubOutWithMock(rsrc.clb, 'create')
        fake_loadbalancer = FakeLoadBalancer(name=lb_name)
        rsrc.clb.create(lb_name, **lb_body).AndReturn(fake_loadbalancer)
        return (rsrc, fake_loadbalancer)

    def _get_first_resource_name(self, templ):
        return next(k for k in templ['Resources'])

    def _mock_loadbalancer(self, lb_template, expected_name, expected_body):
        t = template_format.parse(json.dumps(lb_template))
        s = utils.parse_stack(t, stack_name=utils.random_name())

        rsrc, fake_loadbalancer = self._mock_create(s.t, s,
                                                    self.
                                                    _get_first_resource_name(
                                                        lb_template),
                                                    expected_name,
                                                    expected_body)
        self.m.StubOutWithMock(fake_loadbalancer, 'get')
        fake_loadbalancer.get().MultipleTimes().AndReturn(None)

        fake_loadbalancer.status = 'ACTIVE'

        return (rsrc, fake_loadbalancer)

    def _set_template(self, templ, **kwargs):
        for k, v in six.iteritems(kwargs):
            templ['Resources'][self._get_first_resource_name(templ)][
                'Properties'][k] = v
        return templ

    def _set_expected(self, expected, **kwargs):
        for k, v in six.iteritems(kwargs):
            expected[k] = v
        return expected

    def test_process_node(self):
        nodes = [{'addresses': ['1234'], 'port': 80, 'enabled': True},
                 {'addresses': ['4567', '8901', '8903'], 'port': 80,
                  'enabled': True}]
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        expected_nodes = [{'address': '1234', 'port': 80, 'enabled': True},
                          {'address': '4567', 'port': 80, 'enabled': True},
                          {'address': '8901', 'port': 80, 'enabled': True},
                          {'address': '8903', 'port': 80, 'enabled': True}]
        self.assertEqual(expected_nodes, list(rsrc._process_nodes(nodes)))

    def test_nodeless(self):
        """It's possible to create a LoadBalancer resource with no nodes."""
        template = self._set_template(self.lb_template,
                                      nodes=[])
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['nodes'] = []
        rsrc, fake_loadbalancer = self._mock_loadbalancer(
            template, self.lb_name, expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_alter_properties(self):
        #test alter properties functions
        template = self._set_template(self.lb_template,
                                      sessionPersistence='HTTP_COOKIE',
                                      connectionLogging=True,
                                      metadata={'yolo': 'heeyyy_gurl'})

        expected = self._set_expected(self.expected_body,
                                      sessionPersistence=
                                      {'persistenceType': 'HTTP_COOKIE'},
                                      connectionLogging={'enabled': True},
                                      metadata=[
                                          {'key': 'yolo',
                                           'value': 'heeyyy_gurl'}])

        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_validate_vip(self):
        snippet = {
            "nodes": [],
            "protocol": 'HTTP',
            "port": 80,
            "halfClosed": None,
            "algorithm": u'LEAST_CONNECTIONS',
            "virtualIps": [{"id": "1234"}]
        }
        stack = mock.Mock()
        stack.db_resource_get.return_value = None
        # happy path
        resdef = rsrc_defn.ResourceDefinition("testvip",
                                              lb.CloudLoadBalancer,
                                              properties=snippet)
        rsrc = lb.CloudLoadBalancer("testvip", resdef, stack)
        self.assertIsNone(rsrc.validate())
        # make sure the vip id prop is exclusive
        snippet["virtualIps"][0]["type"] = "PUBLIC"
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn("Cannot specify type or version", str(exc))
        # make sure you have to specify type and version if no id
        snippet["virtualIps"] = [{}]
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn("Must specify VIP type and version", str(exc))

    def test_validate_half_closed(self):
        #test failure (invalid protocol)
        template = self._set_template(self.lb_template, halfClosed=True)
        expected = self._set_expected(self.expected_body, halfClosed=True)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn('The halfClosed property is only available for the TCP'
                      ' or TCP_CLIENT_FIRST protocols', str(exc))

        #test TCP protocol
        template = self._set_template(template, protocol='TCP')
        expected = self._set_expected(expected, protocol='TCP')
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)
        self.assertIsNone(rsrc.validate())

        #test TCP_CLIENT_FIRST protocol
        template = self._set_template(template,
                                      protocol='TCP_CLIENT_FIRST')
        expected = self._set_expected(expected,
                                      protocol='TCP_CLIENT_FIRST')
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)
        self.assertIsNone(rsrc.validate())

    def test_validate_health_monitor(self):
        #test connect success
        health_monitor = {
            'type': 'CONNECT',
            'attemptsBeforeDeactivation': 1,
            'delay': 1,
            'timeout': 1
        }
        template = self._set_template(self.lb_template,
                                      healthMonitor=health_monitor)
        expected = self._set_expected(self.expected_body,
                                      healthMonitor=health_monitor)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)

        self.assertIsNone(rsrc.validate())

        #test connect failure
        #bodyRegex is only valid for type 'HTTP(S)'
        health_monitor['bodyRegex'] = 'dfawefawe'
        template = self._set_template(template,
                                      healthMonitor=health_monitor)
        expected = self._set_expected(expected,
                                      healthMonitor=health_monitor)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn('Unknown Property bodyRegex', str(exc))

        #test http fields
        health_monitor['type'] = 'HTTP'
        health_monitor['bodyRegex'] = 'bodyRegex'
        health_monitor['statusRegex'] = 'statusRegex'
        health_monitor['hostHeader'] = 'hostHeader'
        health_monitor['path'] = 'path'

        template = self._set_template(template,
                                      healthMonitor=health_monitor)
        expected = self._set_expected(expected,
                                      healthMonitor=health_monitor)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)
        self.assertIsNone(rsrc.validate())

    def test_validate_ssl_termination(self):
        ssl_termination = {
            'privatekey': 'ewfawe',
            'intermediateCertificate': 'fwaefawe',
            'secureTrafficOnly': True
        }

        #test ssl termination enabled without required fields failure
        template = self._set_template(self.lb_template,
                                      sslTermination=ssl_termination)
        expected = self._set_expected(self.expected_body,
                                      sslTermination=ssl_termination)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)

        exc = self.assertRaises(exception.StackValidationFailed, rsrc.validate)
        self.assertIn("Property certificate not assigned", six.text_type(exc))

        ssl_termination['certificate'] = 'dfaewfwef'
        template = self._set_template(template,
                                      sslTermination=ssl_termination)
        expected = self._set_expected(expected,
                                      sslTermination=ssl_termination)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)
        self.assertIsNone(rsrc.validate())

    def test_post_creation_access_list(self):
        access_list = [{"address": '192.168.1.1/0',
                        'type': 'ALLOW'},
                       {'address': '172.165.3.43',
                        'type': 'DENY'}]

        template = self._set_template(self.lb_template,
                                      accessList=access_list)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.StubOutWithMock(fake_loadbalancer, 'add_access_list')
        fake_loadbalancer.add_access_list(access_list)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_ref_id(self):
        """The Reference ID of the resource is the resource ID."""
        template = self._set_template(self.lb_template)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

        self.assertEqual(rsrc.resource_id, rsrc.FnGetRefId())

    def test_post_creation_error_page(self):
        error_page = "REALLY BIG ERROR"

        template = self._set_template(self.lb_template,
                                      errorPage=error_page)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.StubOutWithMock(fake_loadbalancer, 'set_error_page')
        fake_loadbalancer.set_error_page(error_page)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_post_creation_ssl_termination(self):
        ssl_termination = {
            'securePort': 443,
            'privatekey': 'afwefawe',
            'certificate': 'fawefwea',
            'intermediateCertificate': "intermediate_certificate",
            'secureTrafficOnly': False
        }

        template = self._set_template(self.lb_template,
                                      sslTermination=ssl_termination)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.StubOutWithMock(fake_loadbalancer, 'add_ssl_termination')
        fake_loadbalancer.add_ssl_termination(
            ssl_termination['securePort'],
            ssl_termination['privatekey'],
            ssl_termination['certificate'],
            intermediateCertificate=ssl_termination['intermediateCertificate'],
            enabled=True,
            secureTrafficOnly=ssl_termination['secureTrafficOnly'])

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_post_creation_content_caching(self):
        template = self._set_template(self.lb_template,
                                      contentCaching='ENABLED')
        rsrc = self._mock_loadbalancer(template, self.lb_name,
                                       self.expected_body)[0]
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_check(self):
        stack = mock.Mock()
        stack.db_resource_get.return_value = None
        resdef = mock.Mock(spec=rsrc_defn.ResourceDefinition)
        loadbalancer = lb.CloudLoadBalancer("test", resdef, stack)
        loadbalancer._add_event = mock.Mock()
        mock_cloud_lb = mock.Mock()
        mock_get = mock.Mock(return_value=mock_cloud_lb)
        loadbalancer.clb.get = mock_get

        mock_cloud_lb.status = 'ACTIVE'
        scheduler.TaskRunner(loadbalancer.check)()
        self.assertEqual('CHECK', loadbalancer.action)
        self.assertEqual('COMPLETE', loadbalancer.status)

        mock_cloud_lb.status = 'FOOBAR'
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(loadbalancer.check))
        self.assertEqual('CHECK', loadbalancer.action)
        self.assertEqual('FAILED', loadbalancer.status)
        self.assertIn('FOOBAR', str(exc))

        mock_get.side_effect = lb.NotFound('boom')
        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(loadbalancer.check))
        self.assertEqual('CHECK', loadbalancer.action)
        self.assertEqual('FAILED', loadbalancer.status)
        self.assertIn('boom', str(exc))

    def test_update_add_node_by_address(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        fake_loadbalancer.nodes = self.expected_body['nodes']
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        expected_ip = '172.168.1.4'
        update_template['Properties']['nodes'] = [
            {"addresses": ["166.78.103.141"],
             "port": 80,
             "condition": "ENABLED"},
            {"addresses": [expected_ip],
             "port": 80,
             "condition": "ENABLED"}]

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'add_nodes')
        fake_loadbalancer.add_nodes([
            fake_loadbalancer.Node(address=expected_ip,
                                   port=80,
                                   condition='ENABLED')])

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_delete_node_failed(self):
        deleted_node = {'nodes': []}
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        fake_loadbalancer.nodes = self.expected_body['nodes']
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()
        self.assertRaises(ValueError, rsrc.handle_update, {}, {}, deleted_node)
        self.m.VerifyAll()

    def test_resolve_attr_noid(self):
        stack = mock.Mock()
        stack.db_resource_get.return_value = None
        resdef = mock.Mock(spec=rsrc_defn.ResourceDefinition)
        lbres = lb.CloudLoadBalancer("test", resdef, stack)
        self.assertIsNone(lbres._resolve_attribute("PublicIp"))

    def test_update_immutable(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = "updated_name"

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        msg = ("Load Balancer '%s' has a status of 'PENDING_UPDATE' and "
               "is considered immutable." % rsrc.resource_id)
        fake_loadbalancer.update(name="updated_name").AndRaise(Exception(msg))
        fake_loadbalancer.update(name="updated_name").AndReturn(None)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_name(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = "updated_name"

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        fake_loadbalancer.update(name="updated_name")

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_multiple(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = "updated_name"
        update_template['Properties']['algorithm'] = "RANDOM"

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        fake_loadbalancer.update(name="updated_name", algorithm="RANDOM")

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_algorithm(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['algorithm'] = "RANDOM"

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        fake_loadbalancer.update(algorithm="RANDOM")

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_protocol(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['protocol'] = "IMAPS"

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        fake_loadbalancer.update(protocol="IMAPS")

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_half_closed(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['halfClosed'] = True

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        fake_loadbalancer.update(halfClosed=True)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_port(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['port'] = 1234

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        fake_loadbalancer.update(port=1234)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_timeout(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['timeout'] = 120

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'update')
        fake_loadbalancer.update(timeout=120)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_health_monitor_add(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['healthMonitor'] = {
            'type': "HTTP", 'delay': 10, 'timeout': 10,
            'attemptsBeforeDeactivation': 4, 'path': "/",
            'statusRegex': "^[234][0-9][0-9]$", 'bodyRegex': ".* testing .*",
            'hostHeader': "example.com"}

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'add_health_monitor')
        fake_loadbalancer.add_health_monitor(
            attemptsBeforeDeactivation=4, bodyRegex='.* testing .*', delay=10,
            hostHeader='example.com', path='/',
            statusRegex='^[234][0-9][0-9]$', timeout=10, type='HTTP')

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_health_monitor_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        hm = {'type': "HTTP", 'delay': 10, 'timeout': 10,
              'attemptsBeforeDeactivation': 4, 'path': "/",
              'statusRegex': "^[234][0-9][0-9]$", 'bodyRegex': ".* testing .*",
              'hostHeader': "example.com"}
        template['Resources'][lb_name]['Properties']['healthMonitor'] = hm
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['healthMonitor'] = hm
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['healthMonitor']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'delete_health_monitor')
        fake_loadbalancer.delete_health_monitor()

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_session_persistence_add(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['sessionPersistence'] = 'SOURCE_IP'

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('SOURCE_IP', fake_loadbalancer.session_persistence)
        self.m.VerifyAll()

    def test_update_session_persistence_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['sessionPersistence'] = \
            "SOURCE_IP"
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['sessionPersistence'] = {'persistenceType': "SOURCE_IP"}
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['sessionPersistence']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('', fake_loadbalancer.session_persistence)
        self.m.VerifyAll()

    def test_update_ssl_termination_add(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['sslTermination'] = {
            'securePort': 443, 'privatekey': private_key, 'certificate': cert,
            'secureTrafficOnly': False}

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'add_ssl_termination')
        fake_loadbalancer.add_ssl_termination(
            securePort=443, privatekey=private_key, certificate=cert,
            secureTrafficOnly=False, intermediateCertificate=None)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_ssl_termination_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['sslTermination'] = {
            'securePort': 443, 'privatekey': private_key, 'certificate': cert,
            'secureTrafficOnly': False}
        # The SSL termination config is done post-creation, so no need
        # to modify self.expected_body
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['sslTermination']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'delete_ssl_termination')
        fake_loadbalancer.delete_ssl_termination()

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_metadata_add(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['metadata'] = {'a': 1, 'b': 2}

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'set_metadata')
        fake_loadbalancer.set_metadata({'a': 1, 'b': 2})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_metadata_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['metadata'] = {
            'a': 1, 'b': 2}
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['metadata'] = [{'key': 'a', 'value': 1},
                                     {'key': 'b', 'value': 2}]
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['metadata']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'delete_metadata')
        fake_loadbalancer.delete_metadata()

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_errorpage_add(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        error_page = (
            '<html><head><title>Service Unavailable</title></head><body><h2>'
            'Service Unavailable</h2>The service is unavailable</body></html>')

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['errorPage'] = error_page

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'set_error_page')
        fake_loadbalancer.set_error_page(error_page)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_errorpage_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        error_page = (
            '<html><head><title>Service Unavailable</title></head><body><h2>'
            'Service Unavailable</h2>The service is unavailable</body></html>')
        template['Resources'][lb_name]['Properties']['errorPage'] = error_page
        # The error page config is done post-creation, so no need to
        # modify self.expected_body
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['errorPage']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'clear_error_page')
        fake_loadbalancer.clear_error_page()

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_connection_logging_enable(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['connectionLogging'] = True

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(True, fake_loadbalancer.connection_logging)
        self.m.VerifyAll()

    def test_update_connection_logging_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['connectionLogging'] = \
            True
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['connectionLogging'] = {'enabled': True}
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['connectionLogging']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(False, fake_loadbalancer.connection_logging)
        self.m.VerifyAll()

    def test_update_connection_logging_disable(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['connectionLogging'] = \
            True
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['connectionLogging'] = {'enabled': True}
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['connectionLogging'] = False

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(False, fake_loadbalancer.connection_logging)
        self.m.VerifyAll()

    def test_update_connection_throttle_add(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['connectionThrottle'] = {
            'maxConnections': 1000}

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'add_connection_throttle')
        fake_loadbalancer.add_connection_throttle(
            maxConnections=1000, maxConnectionRate=None, minConnections=None,
            rateInterval=None)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_connection_throttle_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['connectionThrottle'] = \
            {'maxConnections': 1000}
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['connectionThrottle'] = {
            'maxConnections': 1000, 'maxConnectionRate': None,
            'rateInterval': None, 'minConnections': None}
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['connectionThrottle']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'delete_connection_throttle')
        fake_loadbalancer.delete_connection_throttle()

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_content_caching_enable(self):
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['contentCaching'] = 'ENABLED'

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(True, fake_loadbalancer.content_caching)
        self.m.VerifyAll()

    def test_update_content_caching_deleted(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['contentCaching'] = \
            'ENABLED'
        # Enabling the content cache is done post-creation, so no need
        # to modify self.expected_body
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['contentCaching']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()

        self.assertEqual(True, fake_loadbalancer.content_caching)
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(False, fake_loadbalancer.content_caching)
        self.m.VerifyAll()

    def test_update_content_caching_disable(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = template['Resources'].keys()[0]
        template['Resources'][lb_name]['Properties']['contentCaching'] = \
            'ENABLED'
        # Enabling the content cache is done post-creation, so no need
        # to modify self.expected_body
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          self.expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['contentCaching'] = 'DISABLED'

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.ReplayAll()

        self.assertEqual(True, fake_loadbalancer.content_caching)
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual(False, fake_loadbalancer.content_caching)
        self.m.VerifyAll()
