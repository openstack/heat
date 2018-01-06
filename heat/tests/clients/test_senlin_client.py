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
from openstack import exceptions

from heat.engine.clients.os import senlin as senlin_plugin
from heat.tests import common
from heat.tests import utils


class SenlinClientPluginTest(common.HeatTestCase):
    @mock.patch('openstack.connection.Connection')
    def setUp(self, mock_connection):
        super(SenlinClientPluginTest, self).setUp()
        context = utils.dummy_context()
        self.plugin = context.clients.client_plugin('senlin')
        self.client = self.plugin.client()

    def test_cluster_get(self):
        self.assertIsNotNone(self.client.clusters)

    def test_is_bad_request(self):
        self.assertTrue(self.plugin.is_bad_request(
            exceptions.HttpException(http_status=400)))
        self.assertFalse(self.plugin.is_bad_request(Exception))
        self.assertFalse(self.plugin.is_bad_request(
            exceptions.HttpException(http_status=404)))

    def test_check_action_success(self):
        mock_action = mock.MagicMock()
        mock_action.status = 'SUCCEEDED'
        mock_get = self.patchobject(self.client, 'get_action')
        mock_get.return_value = mock_action
        self.assertTrue(self.plugin.check_action_status('fake_id'))
        mock_get.assert_called_once_with('fake_id')

    def test_get_profile_id(self):
        mock_profile = mock.Mock(id='fake_profile_id')
        mock_get = self.patchobject(self.client, 'get_profile',
                                    return_value=mock_profile)
        ret = self.plugin.get_profile_id('fake_profile')
        self.assertEqual('fake_profile_id', ret)
        mock_get.assert_called_once_with('fake_profile')

    def test_get_cluster_id(self):
        mock_cluster = mock.Mock(id='fake_cluster_id')
        mock_get = self.patchobject(self.client, 'get_cluster',
                                    return_value=mock_cluster)
        ret = self.plugin.get_cluster_id('fake_cluster')
        self.assertEqual('fake_cluster_id', ret)
        mock_get.assert_called_once_with('fake_cluster')

    def test_get_policy_id(self):
        mock_policy = mock.Mock(id='fake_policy_id')
        mock_get = self.patchobject(self.client, 'get_policy',
                                    return_value=mock_policy)
        ret = self.plugin.get_policy_id('fake_policy')
        self.assertEqual('fake_policy_id', ret)
        mock_get.assert_called_once_with('fake_policy')


class ProfileConstraintTest(common.HeatTestCase):

    @mock.patch('openstack.connection.Connection')
    def setUp(self, mock_connection):
        super(ProfileConstraintTest, self).setUp()
        self.senlin_client = mock.MagicMock()
        self.ctx = utils.dummy_context()
        self.mock_get_profile = mock.Mock()
        self.ctx.clients.client(
            'senlin').get_profile = self.mock_get_profile
        self.constraint = senlin_plugin.ProfileConstraint()

    def test_validate_true(self):
        self.mock_get_profile.return_value = None
        self.assertTrue(self.constraint.validate("PROFILE_ID", self.ctx))

    def test_validate_false(self):
        self.mock_get_profile.side_effect = exceptions.ResourceNotFound(
            'PROFILE_ID')
        self.assertFalse(self.constraint.validate("PROFILE_ID", self.ctx))
        self.mock_get_profile.side_effect = exceptions.HttpException(
            'PROFILE_ID')
        self.assertFalse(self.constraint.validate("PROFILE_ID", self.ctx))


class ClusterConstraintTest(common.HeatTestCase):

    @mock.patch('openstack.connection.Connection')
    def setUp(self, mock_connection):
        super(ClusterConstraintTest, self).setUp()
        self.senlin_client = mock.MagicMock()
        self.ctx = utils.dummy_context()
        self.mock_get_cluster = mock.Mock()
        self.ctx.clients.client(
            'senlin').get_cluster = self.mock_get_cluster
        self.constraint = senlin_plugin.ClusterConstraint()

    def test_validate_true(self):
        self.mock_get_cluster.return_value = None
        self.assertTrue(self.constraint.validate("CLUSTER_ID", self.ctx))

    def test_validate_false(self):
        self.mock_get_cluster.side_effect = exceptions.ResourceNotFound(
            'CLUSTER_ID')
        self.assertFalse(self.constraint.validate("CLUSTER_ID", self.ctx))
        self.mock_get_cluster.side_effect = exceptions.HttpException(
            'CLUSTER_ID')
        self.assertFalse(self.constraint.validate("CLUSTER_ID", self.ctx))


class PolicyConstraintTest(common.HeatTestCase):

    @mock.patch('openstack.connection.Connection')
    def setUp(self, mock_connection):
        super(PolicyConstraintTest, self).setUp()
        self.senlin_client = mock.MagicMock()
        self.ctx = utils.dummy_context()
        self.mock_get_policy = mock.Mock()
        self.ctx.clients.client(
            'senlin').get_policy = self.mock_get_policy
        self.constraint = senlin_plugin.PolicyConstraint()

    def test_validate_true(self):
        self.mock_get_policy.return_value = None
        self.assertTrue(self.constraint.validate("POLICY_ID", self.ctx))

    def test_validate_false(self):
        self.mock_get_policy.side_effect = exceptions.ResourceNotFound(
            'POLICY_ID')
        self.assertFalse(self.constraint.validate("POLICY_ID", self.ctx))
        self.mock_get_policy.side_effect = exceptions.HttpException(
            'POLICY_ID')
        self.assertFalse(self.constraint.validate("POLICY_ID", self.ctx))


class ProfileTypeConstraintTest(common.HeatTestCase):

    @mock.patch('openstack.connection.Connection')
    def setUp(self, mock_connection):
        super(ProfileTypeConstraintTest, self).setUp()
        self.senlin_client = mock.MagicMock()
        self.ctx = utils.dummy_context()
        heat_profile_type = mock.MagicMock()
        heat_profile_type.name = 'os.heat.stack-1.0'
        nova_profile_type = mock.MagicMock()
        nova_profile_type.name = 'os.nova.server-1.0'
        self.mock_profile_types = mock.Mock(
            return_value=[heat_profile_type, nova_profile_type])
        self.ctx.clients.client(
            'senlin').profile_types = self.mock_profile_types
        self.constraint = senlin_plugin.ProfileTypeConstraint()

    def test_validate_true(self):
        self.assertTrue(self.constraint.validate("os.heat.stack-1.0",
                                                 self.ctx))

    def test_validate_false(self):
        self.assertFalse(self.constraint.validate("Invalid_type",
                                                  self.ctx))


class PolicyTypeConstraintTest(common.HeatTestCase):

    @mock.patch('openstack.connection.Connection')
    def setUp(self, mock_connection):
        super(PolicyTypeConstraintTest, self).setUp()
        self.senlin_client = mock.MagicMock()
        self.ctx = utils.dummy_context()
        deletion_policy_type = mock.MagicMock()
        deletion_policy_type.name = 'senlin.policy.deletion-1.0'
        lb_policy_type = mock.MagicMock()
        lb_policy_type.name = 'senlin.policy.loadbalance-1.0'
        self.mock_policy_types = mock.Mock(
            return_value=[deletion_policy_type, lb_policy_type])
        self.ctx.clients.client(
            'senlin').policy_types = self.mock_policy_types
        self.constraint = senlin_plugin.PolicyTypeConstraint()

    def test_validate_true(self):
        self.assertTrue(self.constraint.validate(
            "senlin.policy.deletion-1.0", self.ctx))

    def test_validate_false(self):
        self.assertFalse(self.constraint.validate("Invalid_type",
                                                  self.ctx))
