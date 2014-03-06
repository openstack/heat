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

import copy
from migrate.versioning import util as migrate_util
from sqlalchemy.orm import sessionmaker

from heat.openstack.common.gettextutils import _
from heat.db.sqlalchemy import models
from heat.engine.hot.parameters import HOTParamSchema


def upgrade(migrate_engine):
    Session = sessionmaker(bind=migrate_engine)
    session = Session()

    raw_templates = session.query(models.RawTemplate).all()

    for raw_template in raw_templates:
        if ('heat_template_version' in raw_template.template
                and 'parameters' in raw_template.template):

            template = copy.deepcopy(raw_template.template)
            for parameter, schema in template['parameters'].iteritems():
                changed = False

                def _commit_schema(parameter, schema):
                    template['parameters'][parameter] = schema
                    raw_template.template = template
                    session.commit()

                if 'Type' in schema:
                    schema['type'] = schema['Type']
                    del schema['Type']
                    changed = True

                if (schema.get('type') not in HOTParamSchema.TYPES
                        and schema['type'].istitle()):
                    schema['type'] = schema['type'].lower()
                    changed = True

                if changed:
                    _commit_schema(parameter, schema)


def downgrade(migrate_engine):
    migrate_util.log.warning(_('This version cannot be downgraded because '
                               'it involves a data migration to the '
                               'raw_template table.'))
