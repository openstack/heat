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
import uuid

import mock
import mox
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

from ..resources import cloud_loadbalancer as lb  # noqa

# The following fakes are for pyrax


cert = """\n-----BEGIN CERTIFICATE-----
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
-----END CERTIFICATE-----\n"""

private_key = """\n-----BEGIN PRIVATE KEY-----
MIIJRAIBADANBgkqhkiG9w0BAQEFAASCCS4wggkqAgEAAoICAQDJuTXD9LTCh25U
+lHdZPE8Wff/Ljh8FDT27xbL0sgrqY9CdLxgk427gtiOU/wl0bZyxCLfxGq5TQKn
I2wwlrUshCrN8w5ppK3qCAxGvKcgENsnLAlxjMQzfexd/8JS2WoFDTNBcBhy2VgY
OtmzOpfm6U1HF9D6ksr/2lTISfBDw19A8dUWLFcFMyHvx1gu8bwprQwKQKdRcKuw
MJUWilNe7BsD1ifPiPD8qLgXajbrJR5uy0NF7wQOQ35EAOn3gWXiSMjrXLTPVhVk
COXyjrMreT99Ogd2c7cPVWSwJmfKh3sfkdVmNc18QwMChEM/1/G0ajAP1VPDsSXC
tAJmP9b/0xZgJUYdlwQiHPuVBrQnH7Vr2SQLCrq/B4OaT5bhr6bcqkoErEirTlVp
MkwDT9S8jpKQQPCppHqNgil7tUghcqWOUOhPhcvGPEWhyT780TR3JtbZAbxziskb
KOhY78biRMiAvRMlCtNdJ8EJu0LotdVYAkhwaGilb5CGxX0HSmgnrNKEDuXamNPn
wvyBQ4a8Zb0ndlpOyo7jYzbvZFTfQJmtqUU8YWCmjfhrB36C+62uhvR421FVCwHY
wpKN8zihFMxSy39VWWJO4Q4cr/ZKL5NG/LK+VqMMVu/vVstDSli+X9kIFQnKB8PW
xocrmEAnQX87TZijlnvaRo+m0AMeKQIDAQABAoICAA8DuBrDxgiMqAuvLhS6hLIn
SCw4NoAVyPNwTFQTdk65qi4aHkNZ+DyyuoetfKEcAOZ97tKU/hSYxM/H9S+QqB+O
HtmBc9stJLy8qJ1DQXVDi+xYfMN05M2oW8WLWd1szVVe7Ce8vjUeNE5pYvbSL6hC
STw3a5ibAH0WtSTLTBTfH+HnniKuXjPG4InGXqvv1j+L38+LjGilaEIO+6nX1ejE
ziX09LWfzcAglsM3ZqsN8jvw6Sr1ZWniYC2Tm9aOTRUQsdPC7LpZ//GYL/Vj5bYg
qjcZ8KBCcKe1hW8PDL6oYuOwqR+YdZkAK+MuEQtZeWYiWT10dW2la9gYKe2OZuQ1
7q3zZ6zLP+XP+0N7DRMTTuk2gurBVX7VldzIzvjmW8X+8Q5QO+EAqKr2yordK3S1
uYcKmyL4Nd6rSFjRo0zSqHMNOyKt3b1r3m/eR2W623rT5uTjgNYpiwCNxnxmcjpK
Sq7JzZKz9NLbEKQWsP9gQ3G6pp3XfLtoOHEDkSKMmQxd8mzK6Ja/9iC+JGqRTJN+
STe1vL9L2DC7GnjOH1h2TwLoLtQWSGebf/GBxju0e5pAL0UYWBNjAwcpOoRU9J5J
y9E7sNbbXTmK2rg3B/5VKGQckBWfurg7CjAmHGgz9xxceJQLKvT1O5zHZc+v4TVB
XDZjtz8L2k3wFLDynDY5AoIBAQDm2fFgx4vk+gRFXPoLNN34Jw2fT+xuwD/H7K0e
0Cas0NfyNil/Kbp+rhMHuVXTt86BIY+z8GO4wwn+YdDgihBwobAh2G9T/P6wNm+Q
NcIeRioml8V/CP7lOQONQJ6sLTRYnNLfB96uMFe+13DO/PjFybee5VflfBUrJK1M
DqRLwm9wEIf5p0CWYI/ZJaDNN71B09BB/jdT/e7Ro1hXHlq3W4tKqRDPfuUqwy3H
ocYQ1SUk3oFdSiYFd6PijNkfTnrtyToa0xUL9uGL+De1LfgV+uvqkOduQqnpm/5+
XQC1qbTUjq+4WEsuPjYf2E0WAVFGzwzWcdb0LnMIUJHwPvpLAoIBAQDfsvCZlcFM
nGBk1zUnV3+21CPK+5+X3zLHr/4otQHlGMFL6ZiQManvKMX6a/cT3rG+LvECcXGD
jSsTu7JIt9l8VTpbPaS76htTmQYaAZERitBx1C8zDMuI2O4bjFLUGUX73RyTZdRm
G68IX+7Q7SL8zr/fHjcnk+3yj0L1soAVPC7lY3se7vQ/SCre97E+noP5yOhrpnRt
dij7NYy79xcvUZfc/z0//Ia4JSCcIvv2HO7JZIPzUCVO4sjbUOGsgR9pwwQkwYeP
b5P0MVaPgFnOgo/rz6Uqe+LpeY83SUwc2q8W8bskzTLZEnwSV5bxCY+gIn9KCZSG
8QxuftgIiQDbAoIBAQDQ2oTC5kXulzOd/YxK7z2S8OImLAzf9ha+LaZCplcXKqr0
e4P3hC0xxxN4fXjk3vp5YX+9b9MIqYw1FRIA02gkPmQ3erTd65oQmm88rSY+dYRU
/iKz19OkVnycIsZrR0qAkQFGvrv8I8h+5DMvUTdQ2jrCCwQGnsgYDEqs8OI7mGFx
pcMfXu3UHvCFqMFeaPtUvuk/i1tLJgYWrA2UY+X21V+j4GlREKEMmyCj5/xl5jCA
tr2bRSY49BDVOlCFPl+BGfjzo9z6whU0qRDdXgWA/U7LHOYEn1NSAsuwTzwBHtR3
KdBYm6kI4Ufeb7buHasGwPQAX2X17MAt2ZbvIEsZAoIBAQC4g5dzh5PGhmH4K48b
YU/l1TukzUIJekAfd+ozV4I1nuKppAeEQILD0yTh9zX4vMJtdbiz5DDWapWylCpt
UsBgjsgwxDriCSr7HIhs4QfwqUhf67325MHpoc1dCbS0YBhatDpC1kaI5qLMTJzm
1gL69epLtleWHK2zWjnIAbEmUtr3uMOwczciD3vVKAeZ+BQx72bOjKESPNl2w+fO
jvQfwrR5xEqYQco5j95DC5Q6oAjSM0enZV8wn10/kYpjyKnJieMcEkmnpUgrrpqQ
iTUKYqUlw8OftEopfGwGFT5junmbek57/4nGhTmzw22sac9/LZVC034ghClV5uh4
udDrAoIBAQCJHfBPJmJMT/WtSATTceVDgZiyezWNgH2yLJMqDP6sEuImnLAg2L9M
Yc6LqMcHLj7CyXfy2AEAuYTZwXFSRmVKl6Ycad7sS/hIL1ykvDveRU9VNImexDBq
AJR4GKr6jbRZnBztnRYZTsGA+TcrFc6SwdSPXgz7JQT9uw+JkhLi59m141XBdeRc
NQ/LFgOaxjvRUID81izQaYEyADId7asy+2QVazMDafuALJ23WSUMSXajCXaC6/7N
53RWrOAb+kFRgjuHM8pQkpgnY/Ds0MZxpakFw3Y7PAEL99xyYdR+rE3JOMjPlgr0
LpTt0Xs1OFZxaNpolW5Qis4os7UmmIRV
-----END PRIVATE KEY-----\n"""


class FakeException(Exception):
    pass


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

    def update(self):
        pass

    def delete(self):
        pass


class FakeVirtualIP(object):
    def __init__(self, address=None, port=None, condition=None,
                 ipVersion=None, type=None, id=None):
        self.address = address
        self.port = port
        self.condition = condition
        self.ipVersion = ipVersion
        self.type = type
        self.id = id
        self.ip_version = ipVersion

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
        self.algorithm = "ROUND_ROBIN"
        self.session_persistence = "HTTP_COOKIE"
        self.connection_logging = False
        self.timeout = None
        self.httpsRedirect = False
        self.protocol = None
        self.port = None
        self.name = None
        self.halfClosed = None
        self.content_caching = False

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

    def delete(self, *args, **kwargs):
        pass

    def get_health_monitor(self, *args, **kwargs):
        return {}

    def get_metadata(self, *args, **kwargs):
        return {}

    def get_error_page(self, *args, **kwargs):
        pass

    def get_connection_throttle(self, *args, **kwargs):
        pass

    def get_ssl_termination(self, *args, **kwargs):
        pass

    def get_access_list(self, *args, **kwargs):
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
                               condition=u"ENABLED", type=u"PRIMARY",
                               weight=1)],
            "protocol": u'HTTP',
            "port": 80,
            "virtual_ips": [FakeVirtualIP(type=u"PUBLIC", ipVersion=u"IPV6")],
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
            "timeout": 110,
            "httpsRedirect": False

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

        fake_lb = FakeLoadBalancer(name=lb_name)
        fake_lb.status = 'ACTIVE'
        fake_lb.resource_id = 1234

        self.m.StubOutWithMock(rsrc.clb, 'create')
        rsrc.clb.create(lb_name, **lb_body).AndReturn(fake_lb)

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).MultipleTimes().AndReturn(
            fake_lb)

        return (rsrc, fake_lb)

    def _get_first_resource_name(self, templ):
        return next(k for k in templ['Resources'])

    def _mock_loadbalancer(self, lb_template, expected_name, expected_body):
        t = template_format.parse(json.dumps(lb_template))
        self.stack = utils.parse_stack(t, stack_name=utils.random_name())

        rsrc, fake_lb = self._mock_create(self.stack.t, self.stack,
                                          self.
                                          _get_first_resource_name(
                                              lb_template),
                                          expected_name,
                                          expected_body)
        return (rsrc, fake_lb)

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
                  'enabled': True},
                 {'addresses': [], 'port': 80, 'enabled': True}]
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
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
        rsrc, fake_lb = self._mock_loadbalancer(
            template, self.lb_name, expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_alter_properties(self):
        # test alter properties functions
        template = self._set_template(self.lb_template,
                                      sessionPersistence='HTTP_COOKIE',
                                      connectionLogging=True,
                                      metadata={'yolo': 'heeyyy_gurl'})

        expected = self._set_expected(self.expected_body,
                                      sessionPersistence={
                                          'persistenceType': 'HTTP_COOKIE'},
                                      connectionLogging={'enabled': True},
                                      metadata=[
                                          {'key': 'yolo',
                                           'value': 'heeyyy_gurl'}])

        rsrc, fake_lb = self._mock_loadbalancer(template,
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
        stack.has_cache_data.return_value = False
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
        # test failure (invalid protocol)
        template = self._set_template(self.lb_template, halfClosed=True)
        expected = self._set_expected(self.expected_body, halfClosed=True)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn('The halfClosed property is only available for the TCP'
                      ' or TCP_CLIENT_FIRST protocols', str(exc))

        # test TCP protocol
        template = self._set_template(template, protocol='TCP')
        expected = self._set_expected(expected, protocol='TCP')
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        self.assertIsNone(rsrc.validate())

        # test TCP_CLIENT_FIRST protocol
        template = self._set_template(template,
                                      protocol='TCP_CLIENT_FIRST')
        expected = self._set_expected(expected,
                                      protocol='TCP_CLIENT_FIRST')
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        self.assertIsNone(rsrc.validate())

    def test_validate_health_monitor(self):
        # test connect success
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
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)

        self.assertIsNone(rsrc.validate())

        # test connect failure
        # bodyRegex is only valid for type 'HTTP(S)'
        health_monitor['bodyRegex'] = 'dfawefawe'
        template = self._set_template(template,
                                      healthMonitor=health_monitor)
        expected = self._set_expected(expected,
                                      healthMonitor=health_monitor)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        exc = self.assertRaises(exception.StackValidationFailed,
                                rsrc.validate)
        self.assertIn('Unknown Property bodyRegex', str(exc))

        # test http fields
        health_monitor['type'] = 'HTTP'
        health_monitor['bodyRegex'] = 'bodyRegex'
        health_monitor['statusRegex'] = 'statusRegex'
        health_monitor['hostHeader'] = 'hostHeader'
        health_monitor['path'] = 'path'

        template = self._set_template(template,
                                      healthMonitor=health_monitor)
        expected = self._set_expected(expected,
                                      healthMonitor=health_monitor)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        self.assertIsNone(rsrc.validate())

    def test_validate_ssl_termination(self):
        ssl_termination = {
            'privatekey': 'ewfawe',
            'intermediateCertificate': 'fwaefawe',
            'secureTrafficOnly': True
        }

        # test ssl termination enabled without required fields failure
        template = self._set_template(self.lb_template,
                                      sslTermination=ssl_termination)
        expected = self._set_expected(self.expected_body,
                                      sslTermination=ssl_termination)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)

        exc = self.assertRaises(exception.StackValidationFailed, rsrc.validate)
        self.assertIn("Property certificate not assigned", six.text_type(exc))

        ssl_termination['certificate'] = 'dfaewfwef'
        template = self._set_template(template,
                                      sslTermination=ssl_termination)
        expected = self._set_expected(expected,
                                      sslTermination=ssl_termination)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        self.assertIsNone(rsrc.validate())

    def test_ssl_termination_unstripped_certificates(self):
        ssl_termination_template = {
            'securePort': 443,
            'privatekey': 'afwefawe',
            'certificate': '  \nfawefwea\n     ',
            'intermediateCertificate': "\n\nintermediate_certificate\n",
            'secureTrafficOnly': False
        }
        ssl_termination_api = copy.deepcopy(ssl_termination_template)

        template = self._set_template(self.lb_template,
                                      sslTermination=ssl_termination_template)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.StubOutWithMock(fake_lb, 'get_ssl_termination')
        fake_lb.get_ssl_termination().AndReturn({})
        fake_lb.get_ssl_termination().AndReturn({
            'securePort': 443,
            'certificate': 'fawefwea',
            'intermediateCertificate': "intermediate_certificate",
            'secureTrafficOnly': False,
            'enabled': True,
        })

        self.m.StubOutWithMock(fake_lb, 'add_ssl_termination')
        fake_lb.add_ssl_termination(**ssl_termination_api)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_ssl_termination_intermediateCertificate_None(self):
        ssl_termination_template = {
            'securePort': 443,
            'privatekey': 'afwefawe',
            'certificate': '  \nfawefwea\n     ',
            'intermediateCertificate': None,
            'secureTrafficOnly': False
        }

        template = self._set_template(self.lb_template,
                                      sslTermination=ssl_termination_template)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.StubOutWithMock(fake_lb, 'get_ssl_termination')
        fake_lb.get_ssl_termination().AndReturn({})
        fake_lb.get_ssl_termination().AndReturn({
            'securePort': 443,
            'certificate': 'fawefwea',
            'secureTrafficOnly': False,
            'enabled': True,
        })

        self.m.StubOutWithMock(fake_lb, 'add_ssl_termination')
        add_ssl_termination_args = {
            'securePort': 443,
            'privatekey': 'afwefawe',
            'certificate': '  \nfawefwea\n     ',
            'intermediateCertificate': '',
            'secureTrafficOnly': False
        }
        fake_lb.add_ssl_termination(**add_ssl_termination_args)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_post_creation_access_list(self):
        access_list = [{"address": '192.168.1.1/0',
                        'type': 'ALLOW'},
                       {'address': '172.165.3.43',
                        'type': 'DENY'}]
        api_access_list = [{"address": '192.168.1.1/0', 'id': 1234,
                            'type': 'ALLOW'},
                           {'address': '172.165.3.43', 'id': 3422,
                            'type': 'DENY'}]

        template = self._set_template(self.lb_template,
                                      accessList=access_list)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.StubOutWithMock(fake_lb, 'get_access_list')
        fake_lb.get_access_list().AndReturn([])
        fake_lb.get_access_list().AndReturn(api_access_list)

        self.m.StubOutWithMock(fake_lb, 'add_access_list')
        fake_lb.add_access_list(access_list)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_ref_id(self):
        """The Reference ID of the resource is the resource ID."""
        template = self._set_template(self.lb_template)
        rsrc, fake_lb = self._mock_loadbalancer(template,
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
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.StubOutWithMock(fake_lb, 'get_error_page')
        fake_lb.get_error_page().AndReturn({u'errorpage': {u'content': u''}})
        fake_lb.get_error_page().AndReturn(
            {u'errorpage': {u'content': error_page}})

        self.m.StubOutWithMock(fake_lb, 'set_error_page')
        fake_lb.set_error_page(error_page)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_post_creation_ssl_termination(self):
        ssl_termination_template = {
            'securePort': 443,
            'privatekey': 'afwefawe',
            'certificate': 'fawefwea',
            'intermediateCertificate': "intermediate_certificate",
            'secureTrafficOnly': False
        }
        ssl_termination_api = copy.deepcopy(ssl_termination_template)

        template = self._set_template(self.lb_template,
                                      sslTermination=ssl_termination_template)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.StubOutWithMock(fake_lb, 'get_ssl_termination')
        fake_lb.get_ssl_termination().AndReturn({})
        fake_lb.get_ssl_termination().AndReturn({
            'securePort': 443,
            'certificate': 'fawefwea',
            'intermediateCertificate': "intermediate_certificate",
            'secureTrafficOnly': False,
            'enabled': True,
        })

        self.m.StubOutWithMock(fake_lb, 'add_ssl_termination')
        fake_lb.add_ssl_termination(**ssl_termination_api)

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
        stack.has_cache_data.return_value = False
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
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        fake_lb.nodes = self.expected_body['nodes']
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        expected_ip = '172.168.1.4'
        update_template['Properties']['nodes'] = [
            {"addresses": ["166.78.103.141"],
             "port": 80,
             "condition": "ENABLED",
             "type": "PRIMARY",
             "weight": 1},
            {"addresses": [expected_ip],
             "port": 80,
             "condition": "ENABLED",
             "type": "PRIMARY",
             "weight": 1}]

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.nodes = [
            FakeNode(address=u"172.168.1.4", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"166.78.103.141", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
        ]
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'add_nodes')
        fake_lb.add_nodes([
            fake_lb.Node(address=expected_ip,
                         port=80,
                         condition='ENABLED',
                         type="PRIMARY", weight=1)])

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_resolve_attr_noid(self):
        stack = mock.Mock()
        stack.db_resource_get.return_value = None
        stack.has_cache_data.return_value = False
        resdef = mock.Mock(spec=rsrc_defn.ResourceDefinition)
        lbres = lb.CloudLoadBalancer("test", resdef, stack)
        self.assertIsNone(lbres._resolve_attribute("PublicIp"))

    def test_resolve_attr_virtualips(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        fake_lb.virtual_ips = [FakeVirtualIP(address='1.2.3.4',
                                             type='PUBLIC',
                                             ipVersion="IPv6",
                                             id='test-id')]
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        expected = [{
            'ip_version': 'IPv6',
            'type': 'PUBLIC',
            'id': 'test-id',
            'address': '1.2.3.4'}]
        self.m.ReplayAll()
        self.assertEqual(expected, rsrc._resolve_attribute("virtualIps"))
        self.m.VerifyAll()

    def test_update_nodes_immutable(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        current_nodes = [
            FakeNode(address=u"1.1.1.1", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"2.2.2.2", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"3.3.3.3", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1)
        ]
        fake_lb.nodes = current_nodes
        fake_lb.tracker = "fake_lb"
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        expected_ip = '4.4.4.4'
        update_template['Properties']['nodes'] = [
            {"addresses": ["1.1.1.1"], "port": 80, "condition": "ENABLED",
             "type": "PRIMARY", "weight": 1},
            {"addresses": ["2.2.2.2"], "port": 80, "condition": "DISABLED",
             "type": "PRIMARY", "weight": 1},
            {"addresses": [expected_ip], "port": 80, "condition": "ENABLED",
             "type": "PRIMARY", "weight": 1}
        ]

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.status = "PENDING_UPDATE"
        fake_lb1.tracker = "fake_lb1"

        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)  # ACTIVE

        # Add node `expected_ip`
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)  # PENDING_UPDATE

        fake_lb2 = copy.deepcopy(fake_lb1)
        fake_lb2.status = "ACTIVE"
        fake_lb2.nodes = [
            FakeNode(address=u"1.1.1.1", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"2.2.2.2", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"3.3.3.3", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"4.4.4.4", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
        ]
        fake_lb2.tracker = "fake_lb2"

        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)  # ACTIVE

        # Delete node 3.3.3.3
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)  # PENDING_UPDATE

        fake_lb3 = copy.deepcopy(fake_lb2)
        fake_lb3.status = "ACTIVE"
        fake_lb3.nodes = [
            FakeNode(address=u"1.1.1.1", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"2.2.2.2", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"4.4.4.4", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1)
        ]
        fake_lb3.tracker = "fake_lb3"

        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb3)  # ACTIVE

        # Update node 2.2.2.2
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)  # PENDING_UPDATE

        fake_lb4 = copy.deepcopy(fake_lb3)
        fake_lb4.status = "ACTIVE"
        fake_lb4.nodes = [
            FakeNode(address=u"1.1.1.1", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"2.2.2.2", port=80, condition=u"DISABLED",
                     type="PRIMARY", weight=1),
            FakeNode(address=u"4.4.4.4", port=80, condition=u"ENABLED",
                     type="PRIMARY", weight=1)
        ]
        fake_lb4.tracker = "fake_lb4"

        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb4)  # ACTIVE

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_pending_update_status(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = "updated_name"

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.name = "updated_name"
        fake_lb1.status = "PENDING_UPDATE"  # lb is immutable
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.name = "updated_name"
        fake_lb2.status = "ACTIVE"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_immutable_exception(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = "updated_name"

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)  # initial iteration
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)  # immutable
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.name = "updated_name"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)  # after update

        self.m.StubOutWithMock(fake_lb, 'update')
        msg = ("Load Balancer '%s' has a status of 'PENDING_UPDATE' and "
               "is considered immutable." % rsrc.resource_id)
        fake_lb.update(name="updated_name").AndRaise(Exception(msg))
        fake_lb.update(name="updated_name").AndReturn(None)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_create_immutable_exception(self):
        access_list = [{"address": '192.168.1.1/0',
                        'type': 'ALLOW'},
                       {'address': '172.165.3.43',
                        'type': 'DENY'}]

        template = self._set_template(self.lb_template,
                                      accessList=access_list)
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.StubOutWithMock(fake_lb, 'get_access_list')
        fake_lb.get_access_list().AndReturn({})
        fake_lb.get_access_list().AndReturn({})
        fake_lb.get_access_list().AndReturn(access_list)

        self.m.StubOutWithMock(fake_lb, 'add_access_list')
        msg = ("Load Balancer '%s' has a status of 'PENDING_UPDATE' and "
               "is considered immutable." % rsrc.resource_id)
        fake_lb.add_access_list(access_list).AndRaise(Exception(msg))
        fake_lb.add_access_list(access_list)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

    def test_update_lb_name(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = "updated_name"

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.name = "updated_name"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'update')
        fake_lb.update(name="updated_name")

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_multiple(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['name'] = "updated_name"
        update_template['Properties']['algorithm'] = "RANDOM"

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.name = "updated_name"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.algorithm = "RANDOM"
        fake_lb2.name = "updated_name"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)

        self.m.StubOutWithMock(fake_lb, 'update')
        fake_lb.update(name="updated_name", algorithm="RANDOM")

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_algorithm(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['algorithm'] = "RANDOM"

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.algorithm = "ROUND_ROBIN"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb1, 'update')
        fake_lb1.update(algorithm="RANDOM")

        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.algorithm = "RANDOM"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_protocol(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['protocol'] = "IMAPS"

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.protocol = "IMAPS"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'update')
        fake_lb.update(protocol="IMAPS")

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_redirect(self):
        template = self._set_template(
            self.lb_template, protocol="HTTPS")

        expected = self._set_expected(
            self.expected_body, protocol="HTTPS")

        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['httpsRedirect'] = True

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.httpsRedirect = True
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'update')
        fake_lb.update(httpsRedirect=True)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_lb_redirect_https(self):
        template = self._set_template(
            self.lb_template, protocol="HTTPS", httpsRedirect=True)

        expected = self._set_expected(
            self.expected_body, protocol="HTTPS", httpsRedirect=True)

        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_lb_redirect_HTTP_with_SSL_term(self):
        ssl_termination_template = {
            'privatekey': private_key,
            'intermediateCertificate': 'fwaefawe',
            'secureTrafficOnly': True,
            'securePort': 443,
            'certificate': cert
        }
        ssl_termination_api = copy.deepcopy(ssl_termination_template)
        ssl_termination_api['enabled'] = True
        del ssl_termination_api['privatekey']
        template = self._set_template(
            self.lb_template, sslTermination=ssl_termination_template,
            protocol="HTTP", httpsRedirect=True)

        expected = self._set_expected(
            self.expected_body, protocol="HTTP", httpsRedirect=False)

        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected)

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'create')
        rsrc.clb.create(self.lb_name, **expected).AndReturn(fake_lb)
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)

        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.httpsRedirect = True
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'get_ssl_termination')
        fake_lb.get_ssl_termination().AndReturn({})
        fake_lb.get_ssl_termination().AndReturn(ssl_termination_api)
        self.m.StubOutWithMock(fake_lb1, 'get_ssl_termination')
        fake_lb1.get_ssl_termination().AndReturn(ssl_termination_api)
        fake_lb1.get_ssl_termination().AndReturn(ssl_termination_api)
        fake_lb1.get_ssl_termination().AndReturn(ssl_termination_api)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)

    def test_update_lb_half_closed(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['halfClosed'] = True

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.halfClosed = True
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'update')
        fake_lb.update(halfClosed=True)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_port(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['port'] = 1234

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.port = 1234
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'update')
        fake_lb.update(port=1234)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_lb_timeout(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['timeout'] = 120

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.timeout = 120
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb, 'update')
        fake_lb.update(timeout=120)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_health_monitor_add(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
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

        self.m.StubOutWithMock(fake_lb, 'get_health_monitor')
        fake_lb.get_health_monitor().AndReturn({})
        fake_lb.get_health_monitor().AndReturn(
            {'type': "HTTP", 'delay': 10, 'timeout': 10,
             'attemptsBeforeDeactivation': 4, 'path': "/",
             'statusRegex': "^[234][0-9][0-9]$", 'bodyRegex': ".* testing .*",
             'hostHeader': "example.com"})

        self.m.StubOutWithMock(fake_lb, 'add_health_monitor')
        fake_lb.add_health_monitor(
            attemptsBeforeDeactivation=4, bodyRegex='.* testing .*', delay=10,
            hostHeader='example.com', path='/',
            statusRegex='^[234][0-9][0-9]$', timeout=10, type='HTTP')

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_health_monitor_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        hm = {'type': "HTTP", 'delay': 10, 'timeout': 10,
              'attemptsBeforeDeactivation': 4, 'path': "/",
              'statusRegex': "^[234][0-9][0-9]$", 'bodyRegex': ".* testing .*",
              'hostHeader': "example.com"}
        template['Resources'][lb_name]['Properties']['healthMonitor'] = hm
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['healthMonitor'] = hm
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['healthMonitor']

        self.m.StubOutWithMock(fake_lb, 'get_health_monitor')
        fake_lb.get_health_monitor().AndReturn(
            {'type': "HTTP", 'delay': 10, 'timeout': 10,
             'attemptsBeforeDeactivation': 4, 'path': "/",
             'statusRegex': "^[234][0-9][0-9]$", 'bodyRegex': ".* testing .*",
             'hostHeader': "example.com"})
        fake_lb.get_health_monitor().AndReturn({})

        self.m.StubOutWithMock(fake_lb, 'delete_health_monitor')
        fake_lb.delete_health_monitor()

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_session_persistence_add(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['sessionPersistence'] = 'SOURCE_IP'

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('SOURCE_IP', fake_lb.session_persistence)
        self.m.VerifyAll()

    def test_update_session_persistence_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties'][
            'sessionPersistence'] = "SOURCE_IP"
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['sessionPersistence'] = {'persistenceType': "SOURCE_IP"}
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['sessionPersistence']

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertEqual('', fake_lb.session_persistence)
        self.m.VerifyAll()

    def test_update_ssl_termination_add(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['sslTermination'] = {
            'securePort': 443, 'privatekey': private_key, 'certificate': cert,
            'secureTrafficOnly': False, 'intermediateCertificate': ''}

        self.m.StubOutWithMock(fake_lb, 'get_ssl_termination')
        fake_lb.get_ssl_termination().AndReturn({})
        fake_lb.get_ssl_termination().AndReturn({
            'securePort': 443, 'certificate': cert,
            'secureTrafficOnly': False, 'enabled': True})

        self.m.StubOutWithMock(fake_lb, 'add_ssl_termination')
        fake_lb.add_ssl_termination(
            securePort=443, privatekey=private_key, certificate=cert,
            secureTrafficOnly=False, intermediateCertificate='')

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_ssl_termination_delete(self):
        template = copy.deepcopy(self.lb_template)
        ssl_termination_template = {
            'securePort': 443, 'privatekey': private_key, 'certificate': cert,
            'intermediateCertificate': '', 'secureTrafficOnly': False}
        ssl_termination_api = copy.deepcopy(ssl_termination_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties']['sslTermination'] = (
            ssl_termination_template)
        # The SSL termination config is done post-creation, so no need
        # to modify self.expected_body
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)

        self.m.StubOutWithMock(fake_lb, 'get_ssl_termination')
        fake_lb.get_ssl_termination().AndReturn({})

        self.m.StubOutWithMock(fake_lb, 'add_ssl_termination')
        fake_lb.add_ssl_termination(**ssl_termination_api)

        fake_lb.get_ssl_termination().AndReturn({
            'securePort': 443, 'certificate': cert,
            'secureTrafficOnly': False, 'enabled': True})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        self.m.UnsetStubs()
        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['sslTermination']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).MultipleTimes().AndReturn(
            fake_lb)

        self.m.StubOutWithMock(fake_lb, 'get_ssl_termination')
        fake_lb.get_ssl_termination().AndReturn({
            'securePort': 443, 'certificate': cert,
            'secureTrafficOnly': False})

        self.m.StubOutWithMock(fake_lb, 'delete_ssl_termination')
        fake_lb.delete_ssl_termination()

        fake_lb.get_ssl_termination().AndReturn({})

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_metadata_add(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['metadata'] = {'a': 1, 'b': 2}

        self.m.StubOutWithMock(fake_lb, 'get_metadata')
        fake_lb.get_metadata().AndReturn({})
        fake_lb.get_metadata().AndReturn({'a': 1, 'b': 2})

        self.m.StubOutWithMock(fake_lb, 'set_metadata')
        fake_lb.set_metadata({'a': 1, 'b': 2})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_metadata_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties']['metadata'] = {
            'a': 1, 'b': 2}
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['metadata'] = mox.SameElementsAs(
            [{'key': 'a', 'value': 1},
             {'key': 'b', 'value': 2}])
        rsrc, fake_lb = self._mock_loadbalancer(
            template, self.lb_name, expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['metadata']

        self.m.StubOutWithMock(fake_lb, 'get_metadata')
        fake_lb.get_metadata().AndReturn({'a': 1, 'b': 2})
        fake_lb.get_metadata().AndReturn({})

        self.m.StubOutWithMock(fake_lb, 'delete_metadata')
        fake_lb.delete_metadata()

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_errorpage_add(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        error_page = (
            '<html><head><title>Service Unavailable</title></head><body><h2>'
            'Service Unavailable</h2>The service is unavailable</body></html>')

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['errorPage'] = error_page

        self.m.StubOutWithMock(fake_lb, 'get_error_page')
        fake_lb.get_error_page().AndReturn(
            {'errorpage': {'content': 'foo'}})
        fake_lb.get_error_page().AndReturn(
            {'errorpage': {'content': error_page}})

        self.m.StubOutWithMock(fake_lb, 'set_error_page')
        fake_lb.set_error_page(error_page)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_errorpage_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        error_page = (
            '<html><head><title>Service Unavailable</title></head><body><h2>'
            'Service Unavailable</h2>The service is unavailable</body></html>')
        template['Resources'][lb_name]['Properties']['errorPage'] = error_page
        # The error page config is done post-creation, so no need to
        # modify self.expected_body
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)

        self.m.StubOutWithMock(fake_lb, 'get_error_page')
        fake_lb.get_error_page().AndReturn({})

        self.m.StubOutWithMock(fake_lb, 'set_error_page')
        fake_lb.set_error_page(error_page)

        fake_lb.get_error_page().AndReturn({'errorpage':
                                            {'content': error_page}})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        self.m.UnsetStubs()
        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['errorPage']

        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).MultipleTimes().AndReturn(
            fake_lb)

        self.m.StubOutWithMock(fake_lb, 'clear_error_page')
        fake_lb.clear_error_page()

        self.m.StubOutWithMock(fake_lb, 'get_error_page')
        fake_lb.get_error_page().AndReturn(
            {'errorpage': {'content': error_page}})
        fake_lb.get_error_page().AndReturn({'errorpage': {'content': ""}})

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_connection_logging_enable(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['connectionLogging'] = True

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertTrue(fake_lb.connection_logging)
        self.m.VerifyAll()

    def test_update_connection_logging_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties'][
            'connectionLogging'] = True
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['connectionLogging'] = {'enabled': True}
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.connection_logging = True
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.connection_logging = False
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['connectionLogging']

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertFalse(fake_lb.connection_logging)
        self.m.VerifyAll()

    def test_update_connection_logging_disable(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties'][
            'connectionLogging'] = True
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['connectionLogging'] = {'enabled': True}
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['connectionLogging'] = False

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.assertFalse(fake_lb.connection_logging)
        self.m.VerifyAll()

    def test_update_connection_throttle_add(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['connectionThrottle'] = {
            'maxConnections': 1000}

        self.m.StubOutWithMock(fake_lb, 'add_connection_throttle')
        self.m.StubOutWithMock(fake_lb, 'get_connection_throttle')
        fake_lb.get_connection_throttle().AndReturn(
            {'maxConnectionRate': None, 'minConnections': None,
             'rateInterval': None, 'maxConnections': 100})

        fake_lb.add_connection_throttle(
            maxConnections=1000, maxConnectionRate=None, minConnections=None,
            rateInterval=None)

        fake_lb.get_connection_throttle().AndReturn(
            {'maxConnectionRate': None, 'minConnections': None,
             'rateInterval': None, 'maxConnections': 1000})

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_connection_throttle_delete(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties'][
            'connectionThrottle'] = {'maxConnections': 1000}
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['connectionThrottle'] = {
            'maxConnections': 1000, 'maxConnectionRate': None,
            'rateInterval': None, 'minConnections': None}
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['connectionThrottle']

        self.m.StubOutWithMock(fake_lb, 'get_connection_throttle')
        fake_lb.get_connection_throttle().AndReturn({
            'maxConnections': 1000, 'maxConnectionRate': None,
            'rateInterval': None, 'minConnections': None})

        self.m.StubOutWithMock(fake_lb, 'delete_connection_throttle')
        fake_lb.delete_connection_throttle()

        fake_lb.get_connection_throttle().AndReturn({})
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_content_caching_enable(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['contentCaching'] = 'ENABLED'

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.content_caching = False
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.content_caching = True
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_content_caching_deleted(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties'][
            'contentCaching'] = 'ENABLED'
        # Enabling the content cache is done post-creation, so no need
        # to modify self.expected_body
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        del update_template['Properties']['contentCaching']

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.content_caching = True
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.content_caching = False
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_content_caching_disable(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        template['Resources'][lb_name]['Properties'][
            'contentCaching'] = 'ENABLED'
        # Enabling the content cache is done post-creation, so no need
        # to modify self.expected_body
        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                self.expected_body)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['contentCaching'] = 'DISABLED'

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb1.content_caching = True
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.content_caching = False
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete(self):
        template = self._set_template(self.lb_template,
                                      contentCaching='ENABLED')
        rsrc, fake_lb = self._mock_loadbalancer(template, self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()
        self.m.VerifyAll()

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        rsrc.clb.get(mox.IgnoreArg()).AndRaise(lb.NotFound('foo'))
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_immutable(self):
        template = self._set_template(self.lb_template,
                                      contentCaching='ENABLED')
        rsrc, fake_lb = self._mock_loadbalancer(template, self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)
        rsrc.clb.get(mox.IgnoreArg()).AndRaise(lb.NotFound('foo'))

        self.m.StubOutWithMock(fake_lb, 'delete')
        fake_lb.delete().AndRaise(Exception('immutable'))
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_delete_non_immutable_exc(self):
        template = self._set_template(self.lb_template,
                                      contentCaching='ENABLED')
        rsrc, fake_lb = self._mock_loadbalancer(template, self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb)

        self.m.StubOutWithMock(fake_lb, 'delete')
        fake_lb.delete().AndRaise(FakeException())
        self.m.ReplayAll()

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(rsrc.delete))
        self.assertIn('FakeException', six.text_type(exc))
        self.m.VerifyAll()

    def test_delete_states(self):
        template = self._set_template(self.lb_template,
                                      contentCaching='ENABLED')
        rsrc, fake_lb = self._mock_loadbalancer(template, self.lb_name,
                                                self.expected_body)
        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.create)()

        self.m.UnsetStubs()
        fake_lb1 = copy.deepcopy(fake_lb)
        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb3 = copy.deepcopy(fake_lb)
        self.m.StubOutWithMock(rsrc.clb, 'get')

        fake_lb1.status = 'ACTIVE'
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)
        fake_lb2.status = 'PENDING_DELETE'
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)
        fake_lb3.status = 'DELETED'
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb3)

        self.m.ReplayAll()

        scheduler.TaskRunner(rsrc.delete)()
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_redir(self):
        mock_stack = mock.Mock()
        mock_stack.db_resource_get.return_value = None
        mock_stack.has_cache_data.return_value = False
        props = {'httpsRedirect': True,
                 'protocol': 'HTTPS',
                 'port': 443,
                 'nodes': [],
                 'virtualIps': [{'id': '1234'}]}
        mock_resdef = rsrc_defn.ResourceDefinition("test_lb",
                                                   LoadBalancerWithFakeClient,
                                                   properties=props)
        mock_lb = lb.CloudLoadBalancer("test", mock_resdef, mock_stack)
        self.assertIsNone(mock_lb.validate())
        props['protocol'] = 'HTTP'
        props['sslTermination'] = {
            'secureTrafficOnly': True,
            'securePort': 443,
            'privatekey': "bobloblaw",
            'certificate': 'mycert'
        }
        mock_resdef = rsrc_defn.ResourceDefinition("test_lb_2",
                                                   LoadBalancerWithFakeClient,
                                                   properties=props)
        mock_lb = lb.CloudLoadBalancer("test_2", mock_resdef, mock_stack)
        self.assertIsNone(mock_lb.validate())

    def test_invalid_redir_proto(self):
        mock_stack = mock.Mock()
        mock_stack.db_resource_get.return_value = None
        mock_stack.has_cache_data.return_value = False
        props = {'httpsRedirect': True,
                 'protocol': 'TCP',
                 'port': 1234,
                 'nodes': [],
                 'virtualIps': [{'id': '1234'}]}
        mock_resdef = rsrc_defn.ResourceDefinition("test_lb",
                                                   LoadBalancerWithFakeClient,
                                                   properties=props)
        mock_lb = lb.CloudLoadBalancer("test", mock_resdef, mock_stack)
        ex = self.assertRaises(exception.StackValidationFailed,
                               mock_lb.validate)
        self.assertIn("HTTPS redirect is only available", six.text_type(ex))

    def test_invalid_redir_ssl(self):
        mock_stack = mock.Mock()
        mock_stack.db_resource_get.return_value = None
        mock_stack.has_cache_data.return_value = False
        props = {'httpsRedirect': True,
                 'protocol': 'HTTP',
                 'port': 1234,
                 'nodes': [],
                 'virtualIps': [{'id': '1234'}]}
        mock_resdef = rsrc_defn.ResourceDefinition("test_lb",
                                                   LoadBalancerWithFakeClient,
                                                   properties=props)
        mock_lb = lb.CloudLoadBalancer("test", mock_resdef, mock_stack)
        ex = self.assertRaises(exception.StackValidationFailed,
                               mock_lb.validate)
        self.assertIn("HTTPS redirect is only available", six.text_type(ex))
        props['sslTermination'] = {
            'secureTrafficOnly': False,
            'securePort': 443,
            'privatekey': "bobloblaw",
            'certificate': 'mycert'
        }
        mock_lb = lb.CloudLoadBalancer("test", mock_resdef, mock_stack)
        ex = self.assertRaises(exception.StackValidationFailed,
                               mock_lb.validate)
        self.assertIn("HTTPS redirect is only available", six.text_type(ex))
        props['sslTermination'] = {
            'secureTrafficOnly': True,
            'securePort': 1234,
            'privatekey': "bobloblaw",
            'certificate': 'mycert'
        }
        mock_lb = lb.CloudLoadBalancer("test", mock_resdef, mock_stack)
        ex = self.assertRaises(exception.StackValidationFailed,
                               mock_lb.validate)
        self.assertIn("HTTPS redirect is only available", six.text_type(ex))

    def test_update_nodes_condition_draining(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        fake_lb.nodes = self.expected_body['nodes']
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        expected_ip = '172.168.1.4'
        update_template['Properties']['nodes'] = [
            {"addresses": ["166.78.103.141"],
             "port": 80,
             "condition": "DRAINING",
             "type": "PRIMARY",
             "weight": 1},
            {"addresses": [expected_ip],
             "port": 80,
             "condition": "DRAINING",
             "type": "PRIMARY",
             "weight": 1}]

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb1, 'add_nodes')
        fake_lb1.add_nodes([
            fake_lb1.Node(address=expected_ip,
                          port=80,
                          condition='DRAINING',
                          type="PRIMARY", weight=1)])

        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.nodes = [
            FakeNode(address=u"166.78.103.141", port=80,
                     condition=u"DRAINING", type="PRIMARY", weight=1),
            FakeNode(address=u"172.168.1.4", port=80,
                     condition=u"DRAINING", type="PRIMARY", weight=1),
        ]
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_nodes_add_same_address_different_port(self):
        rsrc, fake_lb = self._mock_loadbalancer(self.lb_template,
                                                self.lb_name,
                                                self.expected_body)
        fake_lb.nodes = self.expected_body['nodes']
        fake_lb.tracker = "fake_lb"
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['nodes'] = [
            {"addresses": ["166.78.103.141"],
             "port": 80,
             "condition": "ENABLED",
             "type": "PRIMARY",
             "weight": 1},
            {"addresses": ["166.78.103.141"],
             "port": 81,
             "condition": "ENABLED",
             "type": "PRIMARY",
             "weight": 1}]

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb1, 'add_nodes')
        fake_lb1.add_nodes([
            fake_lb1.Node(address="166.78.103.141",
                          port=81,
                          condition='ENABLED',
                          type="PRIMARY", weight=1)])
        fake_lb1.tracker = "fake_lb1"

        fake_lb2 = copy.deepcopy(fake_lb)
        fake_lb2.nodes = [
            FakeNode(address=u"166.78.103.141", port=80,
                     condition=u"ENABLED", type="PRIMARY", weight=1),
            FakeNode(address=u"166.78.103.141", port=81,
                     condition=u"ENABLED", type="PRIMARY", weight=1),
        ]
        fake_lb2.tracker = "fake_lb2"
        rsrc.clb.get(mox.IgnoreArg()).AndReturn(fake_lb2)

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()

    def test_update_nodes_defaults(self):
        template = copy.deepcopy(self.lb_template)
        lb_name = list(six.iterkeys(template['Resources']))[0]
        tmpl_node = template['Resources'][lb_name]['Properties']['nodes'][0]
        tmpl_node['type'] = "PRIMARY"
        tmpl_node['condition'] = "ENABLED"
        tmpl_node['weight'] = 1
        expected_body = copy.deepcopy(self.expected_body)
        expected_body['nodes'] = [FakeNode(address=u"166.78.103.141", port=80,
                                           condition=u"ENABLED",
                                           type="PRIMARY", weight=1)]

        rsrc, fake_lb = self._mock_loadbalancer(template,
                                                self.lb_name,
                                                expected_body)
        fake_lb.nodes = self.expected_body['nodes']
        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.create)()

        update_template = copy.deepcopy(rsrc.t)
        update_template['Properties']['nodes'] = [
            {"addresses": ["166.78.103.141"],
             "port": 80}]

        self.m.UnsetStubs()
        self.m.StubOutWithMock(rsrc.clb, 'get')
        fake_lb1 = copy.deepcopy(fake_lb)
        rsrc.clb.get(mox.IgnoreArg()).MultipleTimes().AndReturn(fake_lb1)

        self.m.StubOutWithMock(fake_lb1, 'add_nodes')

        self.m.ReplayAll()
        scheduler.TaskRunner(rsrc.update, update_template)()
        self.assertEqual((rsrc.UPDATE, rsrc.COMPLETE), rsrc.state)
        self.m.VerifyAll()
