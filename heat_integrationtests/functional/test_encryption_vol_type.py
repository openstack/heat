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


from heat_integrationtests.common import clients
from heat_integrationtests.common import config
from heat_integrationtests.functional import functional_base

test_encryption_vol_type = {
    'heat_template_version': '2015-04-30',
    'description': 'Test template to create encryption volume type.',
    'resources': {
        'my_volume_type': {
            'type': 'OS::Cinder::VolumeType',
            'properties': {
                'name': 'LUKS'
            }
        },
        'my_encrypted_vol_type': {
            'type': 'OS::Cinder::EncryptedVolumeType',
            'properties': {
                'provider': 'nova.volume.encryptors.luks.LuksEncryptor',
                'control_location': 'front-end',
                'cipher': 'aes-xts-plain64',
                'key_size': 512,
                'volume_type': {'get_resource': 'my_volume_type'}
            }
        }
    }
}


class EncryptionVolTypeTest(functional_base.FunctionalTestsBase):
    def setUp(self):
        super(EncryptionVolTypeTest, self).setUp()
        if not self.conf.admin_username or not self.conf.admin_password:
            self.skipTest('No admin creds found, skipping')
        self.conf = config.init_conf()
        # cinder security policy usage of volume type is limited
        # to being used by administrators only.
        # Temporarily switch to admin
        self.conf.username = self.conf.admin_username
        self.conf.password = self.conf.admin_password
        self.conf.tenant_name = 'admin'
        self.manager = clients.ClientManager(self.conf)
        self.client = self.manager.orchestration_client
        self.volume_client = self.manager.volume_client

    def check_stack(self, sid):
        vt = 'my_volume_type'
        e_vt = 'my_encrypted_vol_type'

        # check if only two resources are present.
        expected_resources = {vt: 'OS::Cinder::VolumeType',
                              e_vt: 'OS::Cinder::EncryptedVolumeType'}
        self.assertEqual(expected_resources,
                         self.list_resources(sid))

        e_vt_obj = self.client.resources.get(sid, e_vt)
        my_encrypted_vol_type_tmpl_prop = test_encryption_vol_type[
            'resources']['my_encrypted_vol_type']['properties']

        # check if the phy rsrc specs was created in accordance with template.
        phy_rsrc_specs = self.volume_client.volume_encryption_types.get(
            e_vt_obj.physical_resource_id)
        self.assertEqual(my_encrypted_vol_type_tmpl_prop['key_size'],
                         phy_rsrc_specs.key_size)
        self.assertEqual(my_encrypted_vol_type_tmpl_prop['provider'],
                         phy_rsrc_specs.provider)
        self.assertEqual(my_encrypted_vol_type_tmpl_prop['cipher'],
                         phy_rsrc_specs.cipher)
        self.assertEqual(my_encrypted_vol_type_tmpl_prop['control_location'],
                         phy_rsrc_specs.control_location)

    def test_create_update(self):
        stack_identifier = self.stack_create(
            template=test_encryption_vol_type)
        self.check_stack(stack_identifier)

        # Change some properties and trigger update.
        my_encrypted_vol_type_tmpl_prop = test_encryption_vol_type[
            'resources']['my_encrypted_vol_type']['properties']
        my_encrypted_vol_type_tmpl_prop['key_size'] = 256
        my_encrypted_vol_type_tmpl_prop['cipher'] = 'aes-cbc-essiv'
        self.update_stack(stack_identifier, test_encryption_vol_type)
        self.check_stack(stack_identifier)
