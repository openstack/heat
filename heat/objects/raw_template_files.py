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


"""RawTemplateFiles object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base
from heat.objects import fields as heat_fields


@heat_base.HeatObjectRegistry.register
class RawTemplateFiles(
    heat_base.HeatObject,
    base.VersionedObjectDictCompat,
    base.ComparableVersionedObject,
):
    # Version 1.0: Initial Version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'files': heat_fields.JsonField(read_only=True),
    }

    @staticmethod
    def _from_db_object(context, tmpl_files, db_tmpl_files):
        for field in tmpl_files.fields:
            tmpl_files[field] = db_tmpl_files[field]

        tmpl_files._context = context
        tmpl_files.obj_reset_changes()
        return tmpl_files

    @classmethod
    def create(cls, context, values):
        return cls._from_db_object(context, cls(),
                                   db_api.raw_template_files_create(context,
                                                                    values))
