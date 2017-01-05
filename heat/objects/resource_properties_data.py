#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""ResourcePropertiesData object."""

from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.common import crypt
from heat.db.sqlalchemy import api as db_api
from heat.objects import fields as heat_fields


class ResourcePropertiesData(
    base.VersionedObject,
    base.VersionedObjectDictCompat,
    base.ComparableVersionedObject,
):
    fields = {
        'id': fields.IntegerField(),
        'data': heat_fields.JsonField(nullable=True),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(rpd, context, db_rpd, data_unencrypted=None):
        # The data_unencrypted field allows us to avoid an extra
        # decrypt operation, e.g. when called from create().
        for field in rpd.fields:
            rpd[field] = db_rpd[field]
        if data_unencrypted:  # save a little (decryption) processing
            rpd['data'] = data_unencrypted
        elif db_rpd['encrypted'] and rpd['data'] is not None:
            rpd['data'] = crypt.decrypted_dict(rpd['data'])

        rpd.obj_reset_changes()
        return rpd

    @classmethod
    def create(cls, context, data):
        properties_data_encrypted, properties_data = \
            ResourcePropertiesData.encrypt_properties_data(data)
        values = {'encrypted': properties_data_encrypted,
                  'data': properties_data}
        db_obj = db_api.resource_prop_data_create(context, values)
        return cls._from_db_object(cls(), context, db_obj, data)

    @staticmethod
    def encrypt_properties_data(data):
        if cfg.CONF.encrypt_parameters_and_properties and data:
            result = {}
            for prop_name, prop_value in data.items():
                prop_string = jsonutils.dumps(prop_value)
                encrypted_value = crypt.encrypt(prop_string)
                result[prop_name] = encrypted_value
            return (True, result)
        return (False, data)
