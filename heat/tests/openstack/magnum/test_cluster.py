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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import magnum as mc
from heat.engine.clients.os import nova
from heat.engine import resource
from heat.engine.resources.openstack.magnum import cluster
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils


magnum_template = '''
    heat_template_version: ocata
    resources:
      test_cluster:
        type: OS::Magnum::Cluster
        properties:
          name: test_cluster
          keypair: key
          cluster_template: 123456
          node_count: 5
          master_count: 1
          discovery_url: https://discovery.etcd.io
          create_timeout: 15
      test_cluster_min:
        type: OS::Magnum::Cluster
        properties:
          cluster_template: 123456
'''

RESOURCE_TYPE = 'OS::Magnum::Cluster'


class TestMagnumCluster(common.HeatTestCase):
    def setUp(self):
        super(TestMagnumCluster, self).setUp()
        resource._register_class(RESOURCE_TYPE, cluster.Cluster)
        t = template_format.parse(magnum_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.min_rsrc_defn = resource_defns['test_cluster_min']
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['test_cluster']
        self.client = mock.Mock()
        self.patchobject(cluster.Cluster, 'client', return_value=self.client)
        self.m_fct = self.patchobject(mc.MagnumClientPlugin,
                                      'get_cluster_template')
        self.m_fnk = self.patchobject(nova.NovaClientPlugin,
                                      'get_keypair', return_value='key')

    def _create_resource(self, name, snippet, stack, stat='CREATE_COMPLETE'):
        self.resource_id = '12345'
        self.m_fct.return_value = '123456'
        value = mock.MagicMock(uuid=self.resource_id)
        self.client.clusters.create.return_value = value
        get_rv = mock.MagicMock(status=stat)
        self.client.clusters.get.return_value = get_rv
        b = cluster.Cluster(name, snippet, stack)
        return b

    def test_cluster_create(self):
        b = self._create_resource('cluster', self.rsrc_defn, self.stack)
        # validate the properties
        self.assertEqual(
            'test_cluster',
            b.properties.get(cluster.Cluster.NAME))
        self.assertEqual(
            '123456',
            b.properties.get(cluster.Cluster.CLUSTER_TEMPLATE))
        self.assertEqual(
            'key',
            b.properties.get(cluster.Cluster.KEYPAIR))
        self.assertEqual(
            5,
            b.properties.get(cluster.Cluster.NODE_COUNT))
        self.assertEqual(
            1,
            b.properties.get(cluster.Cluster.MASTER_COUNT))
        self.assertEqual(
            'https://discovery.etcd.io',
            b.properties.get(cluster.Cluster.DISCOVERY_URL))
        self.assertEqual(
            15,
            b.properties.get(cluster.Cluster.CREATE_TIMEOUT))
        scheduler.TaskRunner(b.create)()
        self.assertEqual(self.resource_id, b.resource_id)
        self.assertEqual((b.CREATE, b.COMPLETE), b.state)
        self.client.clusters.create.assert_called_once_with(
            name=u'test_cluster',
            keypair=u'key',
            cluster_template_id='123456',
            node_count=5,
            master_count=1,
            discovery_url=u'https://discovery.etcd.io',
            create_timeout=15)

    def test_cluster_create_with_default_value(self):
        b = self._create_resource('cluster', self.min_rsrc_defn,
                                  self.stack)
        # validate the properties
        self.assertEqual(
            None,
            b.properties.get(cluster.Cluster.NAME))
        self.assertEqual(
            '123456',
            b.properties.get(cluster.Cluster.CLUSTER_TEMPLATE))
        self.assertEqual(
            None,
            b.properties.get(cluster.Cluster.KEYPAIR))
        self.assertEqual(
            1,
            b.properties.get(cluster.Cluster.NODE_COUNT))
        self.assertEqual(
            1,
            b.properties.get(cluster.Cluster.MASTER_COUNT))
        self.assertEqual(
            None,
            b.properties.get(cluster.Cluster.DISCOVERY_URL))
        self.assertEqual(
            60,
            b.properties.get(cluster.Cluster.CREATE_TIMEOUT))
        scheduler.TaskRunner(b.create)()
        self.assertEqual(self.resource_id, b.resource_id)
        self.assertEqual((b.CREATE, b.COMPLETE), b.state)
        self.client.clusters.create.assert_called_once_with(
            name=None,
            keypair=None,
            cluster_template_id='123456',
            node_count=1,
            master_count=1,
            discovery_url=None,
            create_timeout=60)

    def test_cluster_create_failed(self):
        cfg.CONF.set_override('action_retry_limit', 0, enforce_type=True)
        b = self._create_resource('cluster', self.rsrc_defn, self.stack,
                                  stat='CREATE_FAILED')
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(b.create))
        self.assertIn("Failed to create Cluster", six.text_type(exc))

    def test_cluster_create_unknown_status(self):
        b = self._create_resource('cluster', self.rsrc_defn, self.stack,
                                  stat='CREATE_FOO')
        exc = self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(b.create))
        self.assertIn("Unknown status creating Cluster", six.text_type(exc))

    def _cluster_update(self, update_status='UPDATE_COMPLETE', exc_msg=None):
        b = self._create_resource('cluster', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        status = mock.MagicMock(status=update_status)
        self.client.clusters.get.return_value = status
        t = template_format.parse(magnum_template)
        new_t = copy.deepcopy(t)
        new_t['resources']['test_cluster']['properties']['node_count'] = 10
        rsrc_defns = template.Template(new_t).resource_definitions(self.stack)
        new_bm = rsrc_defns['test_cluster']
        if update_status == 'UPDATE_COMPLETE':
            scheduler.TaskRunner(b.update, new_bm)()
            self.assertEqual((b.UPDATE, b.COMPLETE), b.state)
        else:
            exc = self.assertRaises(
                exception.ResourceFailure,
                scheduler.TaskRunner(b.update, new_bm))
            self.assertIn(exc_msg, six.text_type(exc))

    def test_cluster_update(self):
        self._cluster_update()

    def test_cluster_update_failed(self):
        self._cluster_update('UPDATE_FAILED', 'Failed to update Cluster')

    def test_cluster_update_unknown_status(self):
        self._cluster_update('UPDATE_BAR', 'Unknown status updating Cluster')

    def test_cluster_delete(self):
        b = self._create_resource('cluster', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        b.client_plugin = mock.MagicMock()
        self.client.clusters.get.side_effect = Exception('Not Found')
        self.client.get.reset_mock()
        scheduler.TaskRunner(b.delete)()
        self.assertEqual((b.DELETE, b.COMPLETE), b.state)
        self.assertEqual(2, self.client.clusters.get.call_count)

    def test_cluster_get_live_state(self):
        b = self._create_resource('cluster', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(b.create)()
        value = mock.MagicMock()
        value.to_dict.return_value = {
            'cluster_template': 123456,
            'node_count': 5,
            'master_count': 1,
            'discovery_url': 'https://discovery.etcd.io',
            'create_timeout': 15}
        self.client.clusters.get.return_value = value
        reality = b.get_live_state(b.properties)
        self.assertEqual(
            {'create_timeout': 15,
             'discovery_url': 'https://discovery.etcd.io',
             'master_count': 1,
             'node_count': 5
             },
            reality)
