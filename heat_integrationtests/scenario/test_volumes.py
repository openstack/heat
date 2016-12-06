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


from cinderclient import exceptions as cinder_exceptions
from oslo_log import log as logging
import six

from heat_integrationtests.common import exceptions
from heat_integrationtests.scenario import scenario_base

LOG = logging.getLogger(__name__)


class VolumeBackupRestoreIntegrationTest(scenario_base.ScenarioTestsBase):
    """Class is responsible for testing of volume backup."""

    def setUp(self):
        super(VolumeBackupRestoreIntegrationTest, self).setUp()
        self.volume_description = 'A test volume description 123'
        self.volume_size = self.conf.volume_size

    def _cinder_verify(self, volume_id, expected_status='available'):
        self.assertIsNotNone(volume_id)
        volume = self.volume_client.volumes.get(volume_id)
        self.assertIsNotNone(volume)
        self.assertEqual(expected_status, volume.status)
        self.assertEqual(self.volume_size, volume.size)
        self.assertEqual(self.volume_description,
                         volume.display_description)

    def _outputs_verify(self, stack, expected_status='available'):
        self.assertEqual(expected_status,
                         self._stack_output(stack, 'status'))
        self.assertEqual(six.text_type(self.volume_size),
                         self._stack_output(stack, 'size'))
        self.assertEqual(self.volume_description,
                         self._stack_output(stack, 'display_description'))

    def check_stack(self, stack_id, parameters):
        stack = self.client.stacks.get(stack_id)

        # Verify with cinder that the volume exists, with matching details
        volume_id = self._stack_output(stack, 'volume_id')
        self._cinder_verify(volume_id, expected_status='in-use')

        # Verify the stack outputs are as expected
        self._outputs_verify(stack, expected_status='in-use')

        # Delete the stack and ensure a backup is created for volume_id
        # but the volume itself is gone
        self._stack_delete(stack_id)
        self.assertRaises(cinder_exceptions.NotFound,
                          self.volume_client.volumes.get,
                          volume_id)

        backups = self.volume_client.backups.list()
        self.assertIsNotNone(backups)
        backups_filtered = [b for b in backups if b.volume_id == volume_id]
        self.assertEqual(1, len(backups_filtered))
        backup = backups_filtered[0]
        self.addCleanup(self.volume_client.backups.delete, backup.id)

        # Now, we create another stack where the volume is created from the
        # backup created by the previous stack
        try:
            stack_identifier2 = self.launch_stack(
                template_name='test_volumes_create_from_backup.yaml',
                parameters=parameters,
                add_parameters={'backup_id': backup.id})
            stack2 = self.client.stacks.get(stack_identifier2)
        except exceptions.StackBuildErrorException:
            LOG.exception("Halting test due to bug: #1382300")
            return

        # Verify with cinder that the volume exists, with matching details
        volume_id2 = self._stack_output(stack2, 'volume_id')
        self._cinder_verify(volume_id2, expected_status='in-use')

        # Verify the stack outputs are as expected
        self._outputs_verify(stack2, expected_status='in-use')
        testfile_data = self._stack_output(stack2, 'testfile_data')
        self.assertEqual('{"instance1": "Volume Data:ateststring"}',
                         testfile_data)

        # Delete the stack and ensure the volume is gone
        self._stack_delete(stack_identifier2)
        self.assertRaises(cinder_exceptions.NotFound,
                          self.volume_client.volumes.get,
                          volume_id2)

    def test_cinder_volume_create_backup_restore(self):
        """Ensure the 'Snapshot' deletion policy works.

        This requires a more complex test, but it tests several aspects
        of the heat cinder resources:
           1. Create a volume, attach it to an instance, write some data to it
           2. Delete the stack, with 'Snapshot' specified, creates a backup
           3. Check the snapshot has created a volume backup
           4. Create a new stack, where the volume is created from the backup
           5. Verify the test data written in (1) is present in the new volume
        """
        parameters = {
            'key_name': self.keypair_name,
            'instance_type': self.conf.minimal_instance_type,
            'image_id': self.conf.minimal_image_ref,
            'volume_description': self.volume_description,
            'timeout': self.conf.build_timeout,
            'network': self.net['id']
        }

        # Launch stack
        stack_id = self.launch_stack(
            template_name='test_volumes_delete_snapshot.yaml',
            parameters=parameters,
            add_parameters={'volume_size': self.volume_size}
        )

        # Check stack
        self.check_stack(stack_id, parameters)
