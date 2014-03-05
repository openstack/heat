
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

from heat.db.sqlalchemy.types import LongText
from heat.db.sqlalchemy.types import Json

import sqlalchemy


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    software_config = sqlalchemy.Table('software_config', meta, autoload=True)
    software_config.c.config.alter(type=Json)
    software_config.c.io.drop()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    software_config = sqlalchemy.Table('software_config', meta, autoload=True)
    software_config.c.config.alter(type=LongText)

    io = sqlalchemy.Column('io', Json)
    io.create(software_config)
