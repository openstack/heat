
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

import uuid

import sqlalchemy

from migrate.versioning import util as migrate_util
from heat.openstack.common.gettextutils import _


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    event = sqlalchemy.Table('event', meta, autoload=True)
    event.c.id.alter(type=sqlalchemy.String(36), primary_key=True,
                     default=lambda: str(uuid.uuid4()))


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    event = sqlalchemy.Table('event', meta, autoload=True)

    try:
        event.c.id.alter(type=sqlalchemy.Integer, primary_key=True)
    except:
        # NOTE(pafuent): since there is no way to downgrade just passing
        # The same is did in 018_resource_id_uuid.py
        migrate_util.log.warning(_('If you really want to downgrade to this '
                                   'version, you should drop all the records.'
                                   ))
        pass
