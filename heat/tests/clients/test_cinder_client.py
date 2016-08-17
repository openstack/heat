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
"""Tests for :module:'heat.engine.clients.os.cinder'."""

import uuid

from cinderclient import exceptions as cinder_exc
from keystoneauth1 import exceptions as ks_exceptions
import mock

from heat.common import exception
from heat.engine.clients.os import cinder
from heat.tests import common
from heat.tests import utils


class CinderClientPluginTest(common.HeatTestCase):
    """Basic tests for :module:'heat.engine.clients.os.cinder'."""

    def setUp(self):
        super(CinderClientPluginTest, self).setUp()
        self.cinder_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.cinder_plugin = c.client_plugin('cinder')
        self.cinder_plugin.client = lambda: self.cinder_client

    def test_get_volume(self):
        """Tests the get_volume function."""
        volume_id = str(uuid.uuid4())
        my_volume = mock.MagicMock()
        self.cinder_client.volumes.get.return_value = my_volume

        self.assertEqual(my_volume, self.cinder_plugin.get_volume(volume_id))
        self.cinder_client.volumes.get.assert_called_once_with(volume_id)

    def test_get_snapshot(self):
        """Tests the get_volume_snapshot function."""
        snapshot_id = str(uuid.uuid4())
        my_snapshot = mock.MagicMock()
        self.cinder_client.volume_snapshots.get.return_value = my_snapshot

        self.assertEqual(my_snapshot,
                         self.cinder_plugin.get_volume_snapshot(snapshot_id))
        self.cinder_client.volume_snapshots.get.assert_called_once_with(
            snapshot_id)


class VolumeConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(VolumeConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_volume = mock.Mock()
        self.ctx.clients.client_plugin(
            'cinder').get_volume = self.mock_get_volume
        self.constraint = cinder.VolumeConstraint()

    def test_validation(self):
        self.mock_get_volume.return_value = None
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_volume.side_effect = exception.EntityNotFound(
            entity='Volume', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class VolumeSnapshotConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(VolumeSnapshotConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_snapshot = mock.Mock()
        self.ctx.clients.client_plugin(
            'cinder').get_volume_snapshot = self.mock_get_snapshot
        self.constraint = cinder.VolumeSnapshotConstraint()

    def test_validation(self):
        self.mock_get_snapshot.return_value = 'snapshot'
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_snapshot.side_effect = exception.EntityNotFound(
            entity='VolumeSnapshot', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class VolumeTypeConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(VolumeTypeConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_volume_type = mock.Mock()
        self.ctx.clients.client_plugin(
            'cinder').get_volume_type = self.mock_get_volume_type
        self.constraint = cinder.VolumeTypeConstraint()

    def test_validation(self):
        self.mock_get_volume_type.return_value = 'volume_type'
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_volume_type.side_effect = exception.EntityNotFound(
            entity='VolumeType', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class VolumeBackupConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(VolumeBackupConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_volume_backup = mock.Mock()
        self.ctx.clients.client_plugin(
            'cinder').get_volume_backup = self.mock_get_volume_backup
        self.constraint = cinder.VolumeBackupConstraint()

    def test_validation(self):
        self.mock_get_volume_backup.return_value = 'volume_backup'
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        ex = exception.EntityNotFound(entity='Volume backup', name='bar')
        self.mock_get_volume_backup.side_effect = ex
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class QoSSpecsConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(QoSSpecsConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_qos_specs = mock.Mock()
        self.ctx.clients.client_plugin(
            'cinder').get_qos_specs = self.mock_get_qos_specs
        self.constraint = cinder.QoSSpecsConstraint()

    def test_validation(self):
        self.mock_get_qos_specs.return_value = None
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_qos_specs.side_effect = cinder_exc.NotFound(404)
        self.assertFalse(self.constraint.validate("bar", self.ctx))


class CinderClientAPIVersionTest(common.HeatTestCase):

    def test_cinder_api_v3(self):
        ctx = utils.dummy_context()
        self.patchobject(ctx.keystone_session, 'get_endpoint')
        client = ctx.clients.client('cinder')
        self.assertEqual('3.0', client.version)

    def test_cinder_api_v2(self):
        ctx = utils.dummy_context()
        self.patchobject(ctx.keystone_session, 'get_endpoint',
                         side_effect=[ks_exceptions.EndpointNotFound,
                                      None])
        client = ctx.clients.client('cinder')
        self.assertEqual('2.0', client.version)

    def test_cinder_api_not_supported(self):
        ctx = utils.dummy_context()
        self.patchobject(ctx.keystone_session, 'get_endpoint',
                         side_effect=[ks_exceptions.EndpointNotFound,
                                      ks_exceptions.EndpointNotFound])
        self.assertRaises(exception.Error, ctx.clients.client, 'cinder')


class CinderClientPluginExtensionsTest(CinderClientPluginTest):
    """Tests for extensions in cinderclient."""

    def test_has_no_extensions(self):
        self.cinder_client.list_extensions.show_all.return_value = []
        self.assertFalse(self.cinder_plugin.has_extension(
            "encryption"))

    def test_has_no_interface_extensions(self):
        mock_extension = mock.Mock()
        p = mock.PropertyMock(return_value='os-xxxx')
        type(mock_extension).alias = p
        self.cinder_client.list_extensions.show_all.return_value = [
            mock_extension]
        self.assertFalse(self.cinder_plugin.has_extension(
            "encryption"))

    def test_has_os_interface_extension(self):
        mock_extension = mock.Mock()
        p = mock.PropertyMock(return_value='encryption')
        type(mock_extension).alias = p
        self.cinder_client.list_extensions.show_all.return_value = [
            mock_extension]
        self.assertTrue(self.cinder_plugin.has_extension(
            "encryption"))
