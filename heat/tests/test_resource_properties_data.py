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

from oslo_config import cfg

from heat.db.sqlalchemy import models
from heat.objects import resource_properties_data as rpd_object
from heat.tests import common
from heat.tests import utils


class ResourcePropertiesDataTest(common.HeatTestCase):
    def setUp(self):
        super(ResourcePropertiesDataTest, self).setUp()
        self.ctx = utils.dummy_context()

    data = {'prop1': 'string',
            'prop2': {'a': 'dict'},
            'prop3': 1,
            'prop4': ['a', 'list'],
            'prop5': True}

    def _get_rpd_and_db_obj(self):
        rpd_obj = rpd_object.ResourcePropertiesData().create_or_update(
            self.ctx, self.data)
        db_obj = self.ctx.session.query(
            models.ResourcePropertiesData).get(rpd_obj.id)
        self.assertEqual(len(self.data), len(db_obj['data']))
        return rpd_obj, db_obj

    def test_rsrc_prop_data_encrypt(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)
        rpd_obj, db_obj = self._get_rpd_and_db_obj()

        # verify data is encrypted in the db
        self.assertNotEqual(db_obj['data'], self.data)
        for key in self.data:
            self.assertEqual('cryptography_decrypt_v1',
                             db_obj['data'][key][0])

        # verify rpd_obj data is unencrypted
        self.assertEqual(self.data, rpd_obj['data'])

        # verify loading a fresh rpd_obj has decrypted data
        rpd_obj = rpd_object.ResourcePropertiesData._from_db_object(
            rpd_object.ResourcePropertiesData(self.ctx),
            self.ctx, db_obj)
        self.assertEqual(self.data, rpd_obj['data'])

    def test_rsrc_prop_data_no_encrypt(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', False)
        rpd_obj, db_obj = self._get_rpd_and_db_obj()

        # verify data is unencrypted in the db
        self.assertEqual(db_obj['data'], self.data)
