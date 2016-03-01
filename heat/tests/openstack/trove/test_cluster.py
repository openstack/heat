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
from troveclient.openstack.common.apiclient import exceptions as troveexc

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import trove
from heat.engine.resources.openstack.trove import cluster
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


stack_template = '''
heat_template_version: 2013-05-23

resources:

  cluster:
    type: OS::Trove::Cluster
    properties:
      datastore_type: mongodb
      datastore_version: 2.6.1
      instances:
        - flavor: m1.heat
          volume_size: 1
        - flavor: m1.heat
          volume_size: 1
        - flavor: m1.heat
          volume_size: 1
'''


class FakeTroveCluster(object):
    def __init__(self, status='ACTIVE'):
        self.name = 'cluster'
        self.id = '1189aa64-a471-4aa3-876a-9eb7d84089da'
        self.ip = ['10.0.0.1']
        self.instances = [
            {'id': '416b0b16-ba55-4302-bbd3-ff566032e1c1', 'status': status},
            {'id': '965ef811-7c1d-47fc-89f2-a89dfdd23ef2', 'status': status},
            {'id': '3642f41c-e8ad-4164-a089-3891bf7f2d2b', 'status': status}]

    def delete(self):
        pass


class FakeFlavor(object):
    def __init__(self, id, name):
        self.id = id
        self.name = name


class FakeVersion(object):
    def __init__(self, name="2.6.1"):
        self.name = name


class TroveClusterTest(common.HeatTestCase):

    def setUp(self):
        super(TroveClusterTest, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()

        t = template_format.parse(stack_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['cluster']

        self.patcher_client = mock.patch.object(cluster.TroveCluster,
                                                'client')
        mock_client = self.patcher_client.start()
        self.client = mock_client.return_value
        self.troveclient = mock.Mock()
        self.troveclient.flavors.get.return_value = FakeFlavor(1, 'm1.heat')
        self.troveclient.datastore_versions.list.return_value = [FakeVersion()]
        self.patchobject(trove.TroveClientPlugin, 'client',
                         return_value=self.troveclient)

    def tearDown(self):
        super(TroveClusterTest, self).tearDown()
        self.patcher_client.stop()

    def _create_resource(self, name, snippet, stack):
        tc = cluster.TroveCluster(name, snippet, stack)
        self.client.clusters.create.return_value = FakeTroveCluster()
        self.client.clusters.get.return_value = FakeTroveCluster()
        scheduler.TaskRunner(tc.create)()
        return tc

    def test_create(self):
        tc = self._create_resource('cluster', self.rsrc_defn, self.stack)
        expected_state = (tc.CREATE, tc.COMPLETE)
        self.assertEqual(expected_state, tc.state)
        args = self.client.clusters.create.call_args[1]
        self.assertEqual([{'flavorRef': 1, 'volume': {'size': 1}},
                          {'flavorRef': 1, 'volume': {'size': 1}},
                          {'flavorRef': 1, 'volume': {'size': 1}}],
                         args['instances'])
        self.assertEqual('mongodb', args['datastore'])
        self.assertEqual('2.6.1', args['datastore_version'])
        self.assertEqual('1189aa64-a471-4aa3-876a-9eb7d84089da',
                         tc.resource_id)
        self.assertEqual('clusters', tc.entity)

    def test_attributes(self):
        tc = self._create_resource('cluster', self.rsrc_defn, self.stack)
        self.assertEqual(['10.0.0.1'], tc.FnGetAtt('ip'))
        self.assertEqual(['416b0b16-ba55-4302-bbd3-ff566032e1c1',
                          '965ef811-7c1d-47fc-89f2-a89dfdd23ef2',
                          '3642f41c-e8ad-4164-a089-3891bf7f2d2b'],
                         tc.FnGetAtt('instances'))

    def test_delete(self):
        tc = self._create_resource('cluster', self.rsrc_defn, self.stack)
        self.patchobject(tc, 'handle_delete', return_value=None)
        scheduler.TaskRunner(tc.delete)()
        self.assertEqual((tc.DELETE, tc.COMPLETE), tc.state)

    def test_delete_not_found(self):
        tc = self._create_resource('cluster', self.rsrc_defn, self.stack)
        self.client.clusters.get.side_effect = troveexc.NotFound()
        scheduler.TaskRunner(tc.delete)()
        self.assertEqual((tc.DELETE, tc.COMPLETE), tc.state)
        self.client.clusters.get.assert_called_with(tc.resource_id)
        self.assertEqual(2, self.client.clusters.get.call_count)

    def test_validate_ok(self):
        tc = cluster.TroveCluster('cluster', self.rsrc_defn, self.stack)
        self.assertIsNone(tc.validate())

    def test_validate_invalid_dsversion(self):
        self.rsrc_defn['Properties']['datastore_version'] = '2.6.2'
        tc = cluster.TroveCluster('cluster', self.rsrc_defn, self.stack)
        ex = self.assertRaises(exception.StackValidationFailed, tc.validate)
        error_msg = ('Datastore version 2.6.2 for datastore type mongodb is '
                     'not valid. Allowed versions are 2.6.1.')
        self.assertEqual(error_msg, six.text_type(ex))

    def test_validate_invalid_flavor(self):
        self.troveclient.flavors.get.side_effect = troveexc.NotFound()
        self.troveclient.flavors.find.side_effect = troveexc.NotFound()
        self.rsrc_defn['Properties']['instances'][0]['flavor'] = 'm1.small'
        tc = cluster.TroveCluster('cluster', self.rsrc_defn, self.stack)
        ex = self.assertRaises(exception.StackValidationFailed, tc.validate)
        error_msg = ("Property error: "
                     "resources.cluster.properties.instances[0].flavor: "
                     "Error validating value 'm1.small': Not Found (HTTP 404)")
        self.assertEqual(error_msg, six.text_type(ex))
