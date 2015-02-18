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

import time

from migrate.versioning import util as migrate_util
from oslo_serialization import jsonutils
import sqlalchemy
from sqlalchemy.orm import sessionmaker

from heat.common.i18n import _


def upgrade(migrate_engine):
    Session = sessionmaker(bind=migrate_engine)
    session = Session()

    meta = sqlalchemy.MetaData(bind=migrate_engine)

    templ_table = sqlalchemy.Table('raw_template', meta, autoload=True)
    raw_templates = templ_table.select().execute()

    # NOTE (sdake) 2014-04-24 is the date of the Icehouse release.  It is
    # possible that folks could continue to make errors in their templates
    # right up until the release of Icehouse.  For stacks with version dates
    # in the future, they remain unlistable.  This is to prevent future
    # breakage when new versions come out
    patch_date = time.strptime('2014-04-24', '%Y-%m-%d')
    version_map = [('heat_template_version', '2013-05-23'),
                   ('AWSTemplateFormatVersion', '2010-09-09'),
                   ('HeatTemplateFormatVersion', '2012-12-12')]

    for raw_template in raw_templates:
        for key, date in version_map:
            template = jsonutils.loads(raw_template.template)
            if key in template:

                version = template[key]
                try:
                    dt = time.strptime(version, '%Y-%m-%d')
                except (TypeError, ValueError):
                    dt = None

                if dt is None or dt < patch_date:
                    template[key] = date
                    (templ_table.update().
                        where(templ_table.c.id == raw_template.id).
                        values(template=jsonutils.dumps(template)).
                        execute())
                    session.commit()
    session.close()


def downgrade(migrate_engine):
    migrate_util.log.warning(_('This version cannot be downgraded because '
                               'it involves a data migration to the '
                               'raw_template table.'))
