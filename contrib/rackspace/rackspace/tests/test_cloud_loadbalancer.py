
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
import uuid

from heat.common.exception import StackValidationFailed
from heat.common import template_format
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils

from ..resources import cloud_loadbalancer as lb  # noqa

# The following fakes are for pyrax


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

    def action(self, item, action_type, body={}):
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

    def add_access_list(self, *args, **kwargs):
        pass


class LoadBalancerWithFakeClient(lb.CloudLoadBalancer):
    def cloud_lb(self):
        return FakeLoadBalancerClient()


def override_resource():
    return {
        'Rackspace::Cloud::LoadBalancer': LoadBalancerWithFakeClient
    }


class LoadBalancerTest(HeatTestCase):

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
        utils.setup_dummy_db()
        resource._register_class("Rackspace::Cloud::LoadBalancer",
                                 LoadBalancerWithFakeClient)

    def _get_lb_resource_name(self):
        return "lb-" + str(uuid.uuid4())

    def __getattribute__(self, name):
        if name == 'expected_body' or name == 'lb_template':
            return copy.deepcopy(super(LoadBalancerTest, self)
                                 .__getattribute__(name))
        return super(LoadBalancerTest, self).__getattribute__(name)

    def _mock_create(self, t, stack, resource_name, lb_name, lb_body):
        rsrc = LoadBalancerWithFakeClient(resource_name,
                                          t['Resources'][resource_name],
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

        rsrc, fake_loadbalancer = self._mock_create(t, s,
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
        for k, v in kwargs.iteritems():
            templ['Resources'][self._get_first_resource_name(templ)][
                'Properties'][k] = v
        return templ

    def _set_expected(self, expected, **kwargs):
        for k, v in kwargs.iteritems():
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

    def test_validate_half_closed(self):
        #test failure (invalid protocol)
        template = self._set_template(self.lb_template, halfClosed=True)
        expected = self._set_expected(self.expected_body, halfClosed=True)
        rsrc, fake_loadbalancer = self._mock_loadbalancer(template,
                                                          self.lb_name,
                                                          expected)
        self.assertEqual(
            {'Error':
             'The halfClosed property is only available for the '
             'TCP or TCP_CLIENT_FIRST protocols'},
            rsrc.validate())

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
        self.assertEqual({'Error': 'Unknown Property bodyRegex'},
                         rsrc.validate())

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

        exc = self.assertRaises(StackValidationFailed, rsrc.validate)
        self.assertIn("Property certificate not assigned", str(exc))

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

    def test_update_add_node_by_address(self):
        expected_ip = '172.168.1.4'
        added_node = {'nodes': [
            {"address": "166.78.103.141", "port": 80, "condition": "ENABLED"},
            {"address": expected_ip, "port": 80, "condition": "ENABLED"}]}
        rsrc, fake_loadbalancer = self._mock_loadbalancer(self.lb_template,
                                                          self.lb_name,
                                                          self.expected_body)
        fake_loadbalancer.nodes = self.expected_body['nodes']
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(rsrc.resource_id).AndReturn(fake_loadbalancer)

        self.m.StubOutWithMock(fake_loadbalancer, 'add_nodes')
        fake_loadbalancer.add_nodes([
            fake_loadbalancer.Node(address=expected_ip,
                                   port=80,
                                   condition='ENABLED')])

        self.m.ReplayAll()
        rsrc.handle_update({}, {}, added_node)
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
