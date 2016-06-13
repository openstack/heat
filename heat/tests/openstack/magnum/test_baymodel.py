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

import mock
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine.resources.openstack.magnum import baymodel
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


RESOURCE_TYPE = 'OS::Magnum::BayModel'


class TestMagnumBayModel(common.HeatTestCase):
    magnum_template = '''
    heat_template_version: 2015-04-30
    resources:
      test_baymodel:
        type: OS::Magnum::BayModel
        properties:
          name: test_bay_model
          image: fedora-21-atomic-2
          flavor: m1.small
          master_flavor: m1.medium
          keypair: heat_key
          external_network: 0244b54d-ae1f-44f0-a24a-442760f1d681
          fixed_network: 0f59a3dd-fac1-4d03-b41a-d4115fbffa89
          dns_nameserver: 8.8.8.8
          docker_volume_size: 5
          coe: 'swarm'
'''

    expected = {
        'name': 'test_bay_model',
        'image_id': 'fedora-21-atomic-2',
        'flavor_id': 'm1.small',
        'master_flavor_id': 'm1.medium',
        'keypair_id': 'heat_key',
        'external_network_id': '0244b54d-ae1f-44f0-a24a-442760f1d681',
        'fixed_network': '0f59a3dd-fac1-4d03-b41a-d4115fbffa89',
        'dns_nameserver': '8.8.8.8',
        'docker_volume_size': 5,
        'coe': 'swarm',
    }

    def setUp(self):
        super(TestMagnumBayModel, self).setUp()
        resource._register_class(RESOURCE_TYPE, baymodel.BayModel)
        t = template_format.parse(self.magnum_template)
        self.stack = utils.parse_stack(t)

        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['test_baymodel']
        self.client = mock.Mock()
        self.patchobject(baymodel.BayModel, 'client',
                         return_value=self.client)
        self.stub_FlavorConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_ImageConstraint_validate()
        self.stub_NetworkConstraint_validate()

    def _create_resource(self, name, snippet, stack):
        self.resource_id = '12345'
        self.test_bay_model = self.stack['test_baymodel']
        value = mock.MagicMock(uuid=self.resource_id)
        self.client.baymodels.create.return_value = value
        bm = baymodel.BayModel(name, snippet, stack)
        scheduler.TaskRunner(bm.create)()
        return bm

    def test_bay_model_create(self):
        bm = self._create_resource('bm', self.rsrc_defn, self.stack)
        self.assertEqual(self.resource_id, bm.resource_id)
        self.assertEqual((bm.CREATE, bm.COMPLETE), bm.state)
        self.client.baymodels.create.assert_called_once_with(**self.expected)


class TestMagnumBayModelWithAddedProperties(TestMagnumBayModel):
    magnum_template = '''
    heat_template_version: 2015-04-30
    resources:
      test_baymodel:
        type: OS::Magnum::BayModel
        properties:
          name: test_bay_model
          image: fedora-21-atomic-2
          flavor: m1.small
          master_flavor: m1.medium
          keypair: heat_key
          external_network: 0244b54d-ae1f-44f0-a24a-442760f1d681
          fixed_network: 0f59a3dd-fac1-4d03-b41a-d4115fbffa89
          dns_nameserver: 8.8.8.8
          docker_volume_size: 5
          coe: 'mesos'
          network_driver: 'flannel'
          http_proxy: 'http://proxy.com:123'
          https_proxy: 'https://proxy.com:123'
          no_proxy: '192.168.0.1'
          labels: {'flannel_cidr': ['10.101.0.0/16', '10.102.0.0/16']}
          tls_disabled: True
          public: True
          registry_enabled: True
          volume_driver: rexray
    '''
    expected = {
        'name': 'test_bay_model',
        'image_id': 'fedora-21-atomic-2',
        'flavor_id': 'm1.small',
        'master_flavor_id': 'm1.medium',
        'keypair_id': 'heat_key',
        'external_network_id': '0244b54d-ae1f-44f0-a24a-442760f1d681',
        'fixed_network': '0f59a3dd-fac1-4d03-b41a-d4115fbffa89',
        'dns_nameserver': '8.8.8.8',
        'docker_volume_size': 5,
        'coe': 'mesos',
        'network_driver': 'flannel',
        'http_proxy': 'http://proxy.com:123',
        'https_proxy': 'https://proxy.com:123',
        'no_proxy': '192.168.0.1',
        'labels': {'flannel_cidr': ['10.101.0.0/16', '10.102.0.0/16']},
        'tls_disabled': True,
        'public': True,
        'registry_enabled': True,
        'volume_driver': 'rexray'
    }

    def setUp(self):
        super(TestMagnumBayModelWithAddedProperties, self).setUp()
        self.t = template_format.parse(self.magnum_template)

    def test_bay_model_create_with_added_properties(self):
        bm = self._create_resource('bm', self.rsrc_defn, self.stack)
        self.assertEqual(self.resource_id, bm.resource_id)
        self.assertEqual((bm.CREATE, bm.COMPLETE), bm.state)
        self.client.baymodels.create.assert_called_once_with(**self.expected)

    def test_validate_invalid_volume_driver(self):
        props = self.t['resources']['test_baymodel']['properties']
        props['volume_driver'] = 'cinder'
        stack = utils.parse_stack(self.t)
        msg = ("Volume driver type cinder is not supported by COE:mesos, "
               "expecting a ['rexray'] volume driver.")
        ex = self.assertRaises(exception.StackValidationFailed,
                               stack['test_baymodel'].validate)
        self.assertEqual(msg, six.text_type(ex))
