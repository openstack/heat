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

import logging

from cinderclient import exceptions as cinder_exceptions
import six
from testtools import testcase

from heat_integrationtests.common import exceptions
from heat_integrationtests.common import test

LOG = logging.getLogger(__name__)


class VolumeBackupRestoreIntegrationTest(test.HeatIntegrationTest):

    def setUp(self):
        super(VolumeBackupRestoreIntegrationTest, self).setUp()
        self.client = self.orchestration_client
        self.assign_keypair()
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

    def launch_stack(self, template_name, add_parameters={}):
        net = self._get_default_network()
        template = self._load_template(__file__, template_name, 'templates')
        parameters = {'key_name': self.keypair_name,
                      'instance_type': self.conf.instance_type,
                      'image_id': self.conf.minimal_image_ref,
                      'volume_description': self.volume_description,
                      'timeout': self.conf.build_timeout,
                      'network': net['id']}
        parameters.update(add_parameters)
        return self.stack_create(template=template,
                                 parameters=parameters)

    @testcase.skip('Skipped until failure rate '
                   'can be reduced ref bug #1382300')
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
        stack_identifier = self.launch_stack(
            template_name='test_volumes_delete_snapshot.yaml',
            add_parameters={'volume_size': self.volume_size})

        stack = self.client.stacks.get(stack_identifier)

        # Verify with cinder that the volume exists, with matching details
        volume_id = self._stack_output(stack, 'volume_id')
        self._cinder_verify(volume_id, expected_status='in-use')

        # Verify the stack outputs are as expected
        self._outputs_verify(stack, expected_status='in-use')

        # Delete the stack and ensure a backup is created for volume_id
        # but the volume itself is gone
        self.client.stacks.delete(stack_identifier)
        self._wait_for_stack_status(stack_identifier, 'DELETE_COMPLETE')
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
                add_parameters={'backup_id': backup.id})
            stack2 = self.client.stacks.get(stack_identifier2)
        except exceptions.StackBuildErrorException as e:
            LOG.error("Halting test due to bug: #1382300")
            LOG.exception(e)
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
        self.client.stacks.delete(stack_identifier2)
        self._wait_for_stack_status(stack_identifier2, 'DELETE_COMPLETE')
        self.assertRaises(cinder_exceptions.NotFound,
                          self.volume_client.volumes.get,
                          volume_id2)
