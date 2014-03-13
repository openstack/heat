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

import uuid

import mock

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils

from ..resources import cloudnetworks  # noqa

try:
    from pyrax.exceptions import NotFound
except ImportError:
    from ..resources.cloudnetworks import NotFound  # noqa


class FakeNetwork(object):

    def __init__(self, client, label="test_network", cidr="172.16.0.0/24"):
        self.client = client
        self.label = label
        self.cidr = cidr
        self.id = str(uuid.uuid4())

    def _is_deleted(self):
        return (self.client and
                self.id not in [nw.id for nw in self.client.networks])

    def get(self):
        if self._is_deleted():
            raise NotFound("I am deleted")

    def delete(self):
        self.client._delete(self)


class FakeClient(object):

    def __init__(self):
        self.networks = []

    def create(self, label=None, cidr=None):
        nw = FakeNetwork(self, label=label, cidr=cidr)
        self.networks.append(nw)
        return nw

    def get(self, nwid):
        for nw in self.networks:
            if nw.id == nwid:
                return nw
        raise NotFound("No network %s" % nwid)

    def _delete(self, nw):
        try:
            self.networks.remove(nw)
        except ValueError:
            pass


@mock.patch.object(cloudnetworks.CloudNetwork, "cloud_networks")
class CloudNetworkTest(HeatTestCase):

    _template = template_format.parse("""
    heat_template_version: 2013-05-23
    description: Test stack for Rackspace Cloud Networks
    resources:
      cnw:
        type: Rackspace::Cloud::Network
        properties:
          label: test_network
          cidr: 172.16.0.0/24
    """)

    def setUp(self):
        super(CloudNetworkTest, self).setUp()
        utils.setup_dummy_db()
        resource._register_class("Rackspace::Cloud::Network",
                                 cloudnetworks.CloudNetwork)

    def _parse_stack(self):
        self.stack = utils.parse_stack(self._template,
                                       stack_name=self.__class__.__name__)

    def _setup_stack(self, mock_client, *args):
        self.fake_cnw = FakeClient(*args)
        mock_client.return_value = self.fake_cnw
        self._parse_stack()
        self.stack.create()
        self.assertEqual((self.stack.CREATE, self.stack.COMPLETE),
                         self.stack.state)
        res = self.stack['cnw']
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    @utils.stack_delete_after
    def test_attributes(self, mock_client):
        self._setup_stack(mock_client)
        res = self.stack['cnw']
        template_resource = self._template['resources']['cnw']
        expect_label = template_resource['properties']['label']
        expect_cidr = template_resource['properties']['cidr']
        self.assertEqual(expect_label, res.FnGetAtt('label'))
        self.assertEqual(expect_cidr, res.FnGetAtt('cidr'))

    @utils.stack_delete_after
    def test_create_bad_cider(self, mock_client):
        self._template['resources']['cnw']['properties']['cidr'] = "bad cidr"
        self._parse_stack()
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.stack.validate)
        self.assertIn("Invalid cidr", str(exc))

    @utils.stack_delete_after
    def test_delete(self, mock_client):
        self._setup_stack(mock_client)
        res = self.stack['cnw']
        res_id = res.FnGetRefId()
        scheduler.TaskRunner(res.delete)()
        self.assertEqual((res.DELETE, res.COMPLETE), res.state)
        exc = self.assertRaises(NotFound, self.fake_cnw.get, res_id)
        self.assertIn(res_id, str(exc))

    @utils.stack_delete_after
    def test_delete_not_complete(self, mock_client):
        self._setup_stack(mock_client)
        res = self.stack['cnw']
        self.assertFalse(res.check_delete_complete(res.network()))

    @utils.stack_delete_after
    def test_delete_not_found(self, mock_client):
        self._setup_stack(mock_client)
        self.fake_cnw.networks = []
        res = self.stack['cnw']
        scheduler.TaskRunner(res.delete)()
        self.assertEqual((res.DELETE, res.COMPLETE), res.state)
