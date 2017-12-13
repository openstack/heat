# Copyright 2014 Intel Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


"""RawTemplate object."""

import copy

from oslo_config import cfg
from oslo_log import log as logging
from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.common import crypt
from heat.common import environment_format as env_fmt
from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base
from heat.objects import fields as heat_fields

LOG = logging.getLogger(__name__)


@heat_base.HeatObjectRegistry.register
class RawTemplate(
    heat_base.HeatObject,
    base.VersionedObjectDictCompat,
    base.ComparableVersionedObject,
):
    # Version 1.0: Initial version
    # Version 1.1: Added files_id
    VERSION = '1.1'

    fields = {
        'id': fields.IntegerField(),
        # TODO(cwolfe): remove deprecated files in future release
        'files': heat_fields.JsonField(nullable=True),
        'files_id': fields.IntegerField(nullable=True),
        'template': heat_fields.JsonField(),
        'environment': heat_fields.JsonField(),
    }

    @staticmethod
    def from_db_object(context, tpl, db_tpl):
        for field in tpl.fields:
            tpl[field] = db_tpl[field]

        tpl.environment = copy.deepcopy(tpl.environment)
        # If any of the parameters were encrypted, then decrypt them
        if (tpl.environment is not None and
                env_fmt.ENCRYPTED_PARAM_NAMES in tpl.environment):
            parameters = tpl.environment[env_fmt.PARAMETERS]
            encrypted_param_names = tpl.environment[
                env_fmt.ENCRYPTED_PARAM_NAMES]

            for param_name in encrypted_param_names:
                if (isinstance(parameters[param_name], (list, tuple)) and
                        len(parameters[param_name]) == 2):
                    method, enc_value = parameters[param_name]
                    value = crypt.decrypt(method, enc_value)
                else:
                    value = parameters[param_name]
                    LOG.warning(
                        'Encountered already-decrypted data while attempting '
                        'to decrypt parameter %s. Please file a Heat bug so '
                        'this can be fixed.', param_name)
                parameters[param_name] = value
            tpl.environment[env_fmt.PARAMETERS] = parameters

        tpl._context = context
        tpl.obj_reset_changes()
        return tpl

    @classmethod
    def get_by_id(cls, context, template_id):
        raw_template_db = db_api.raw_template_get(context, template_id)
        return cls.from_db_object(context, cls(), raw_template_db)

    @classmethod
    def encrypt_hidden_parameters(cls, tmpl):
        if cfg.CONF.encrypt_parameters_and_properties:
            for param_name in tmpl.env.params.keys():
                if not tmpl.param_schemata()[param_name].hidden:
                    continue
                clear_text_val = tmpl.env.params.get(param_name)
                tmpl.env.params[param_name] = crypt.encrypt(clear_text_val)
                if param_name not in tmpl.env.encrypted_param_names:
                    tmpl.env.encrypted_param_names.append(param_name)

    @classmethod
    def create(cls, context, values):
        return cls.from_db_object(context, cls(),
                                  db_api.raw_template_create(context, values))

    @classmethod
    def update_by_id(cls, context, template_id, values):
        # Only save template files in the new raw_template_files
        # table, not in the old location of raw_template.files
        if 'files_id' in values and values['files_id']:
            values['files'] = None
        return cls.from_db_object(
            context, cls(),
            db_api.raw_template_update(context, template_id, values))

    @classmethod
    def delete(cls, context, template_id):
        db_api.raw_template_delete(context, template_id)
