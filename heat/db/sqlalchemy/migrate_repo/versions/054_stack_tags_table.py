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
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    stack.c.tags.drop()

    stack_tag = sqlalchemy.Table(
        'stack_tag', meta,
        sqlalchemy.Column('id',
                          sqlalchemy.Integer,
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('tag', sqlalchemy.Unicode(80)),
        sqlalchemy.Column('stack_id',
                          sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'),
                          nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    stack_tag.create()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    tags = sqlalchemy.Column('tags', heat_db_types.Json)
    tags.create(stack)

    stack_tag = sqlalchemy.Table('stack_tag', meta, autoload=True)
    stack_tag.drop()
