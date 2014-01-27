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


def upgrade(migrate_engine):
    Session = sessionmaker(bind=migrate_engine)
    session = Session()

    raw_templates = session.query(models.RawTemplate).all()

    CFN_TO_HOT_RESOURCE_ATTRS = {'Type': 'type',
                                 'Properties': 'properties',
                                 'Metadata': 'metadata',
                                 'DependsOn': 'depends_on',
                                 'DeletionPolicy': 'deletion_policy',
                                 'UpdatePolicy': 'update_policy'}

    CFN_TO_HOT_OUTPUT_ATTRS = {'Description': 'description',
                               'Value': 'value'}

    def _translate(section, translate_map):
        changed = False

        for name, details in section.iteritems():
            for old_key, new_key in translate_map.iteritems():
                if old_key in details:
                    details[new_key] = details[old_key]
                    del details[old_key]
                    changed = True

        return changed

    for raw_template in raw_templates:
        if 'heat_template_version' in raw_template.template:

            changed = False
            template = copy.deepcopy(raw_template.template)

            resources = template.get('resources', {})
            if _translate(resources, CFN_TO_HOT_RESOURCE_ATTRS):
                changed = True

            outputs = template.get('outputs', {})
            if _translate(outputs, CFN_TO_HOT_OUTPUT_ATTRS):
                changed = True

            if changed:
                raw_template.template = template
                session.commit()


def downgrade(migrate_engine):
    migrate_util.log.warning(_('This version cannot be downgraded because '
                               'it involves a data migration to the '
                               'raw_template table.'))
