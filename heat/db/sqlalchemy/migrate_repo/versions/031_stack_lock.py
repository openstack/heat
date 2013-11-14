
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


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    stack_lock = sqlalchemy.Table(
        'stack_lock', meta,
        sqlalchemy.Column('stack_id', sqlalchemy.String(length=36),
                          sqlalchemy.ForeignKey('stack.id'),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('engine_id', sqlalchemy.String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    sqlalchemy.Table('stack', meta, autoload=True)
    stack_lock.create()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    stack_lock = sqlalchemy.Table('stack_lock', meta, autoload=True)
    stack_lock.drop()
