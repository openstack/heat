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

import mock

from heat.common import exception
from heat.engine.clients.os import cinder
from heat.tests import common
from heat.tests import utils


class CinderClientPluginTests(common.HeatTestCase):
    """Basic tests for :module:'heat.engine.clients.os.cinder'."""

    def setUp(self):
        super(CinderClientPluginTests, self).setUp()
        self.cinder_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.cinder_plugin = c.client_plugin('cinder')
        self.cinder_plugin._client = self.cinder_client

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
