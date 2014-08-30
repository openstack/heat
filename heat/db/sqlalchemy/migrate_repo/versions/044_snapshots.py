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

import sqlalchemy

from heat.db.sqlalchemy.types import Json


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    snapshot = sqlalchemy.Table(
        'snapshot', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('stack_id',
                          sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'),
                          nullable=False),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('data', Json),
        sqlalchemy.Column('tenant', sqlalchemy.String(64),
                          nullable=False,
                          index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    sqlalchemy.Table('stack', meta, autoload=True)
    snapshot.create()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    snapshot = sqlalchemy.Table('snapshot', meta, autoload=True)
    snapshot.drop()
