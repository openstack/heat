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

from heat.db.sqlalchemy import types as heat_db_types


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    sqlalchemy.Table('stack', meta, autoload=True)

    sync_point = sqlalchemy.Table(
        'sync_point', meta,
        sqlalchemy.Column('entity_id', sqlalchemy.String(36)),
        sqlalchemy.Column('traversal_id', sqlalchemy.String(36)),
        sqlalchemy.Column('is_update', sqlalchemy.Boolean),
        sqlalchemy.Column('atomic_key', sqlalchemy.Integer,
                          nullable=False),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          nullable=False),
        sqlalchemy.Column('input_data', heat_db_types.Json),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),

        sqlalchemy.PrimaryKeyConstraint('entity_id',
                                        'traversal_id',
                                        'is_update'),
        sqlalchemy.ForeignKeyConstraint(['stack_id'], ['stack.id'],
                                        name='fk_stack_id'),

        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    sync_point.create()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    sync_point = sqlalchemy.Table(
        'sync_point', meta, autoload=True)
    sync_point.drop()
