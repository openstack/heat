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

from heat.db.sqlalchemy import utils as migrate_utils


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    parent_resource_name = sqlalchemy.Column('parent_resource_name',
                                             sqlalchemy.String(255))
    parent_resource_name.create(stack)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    if migrate_engine.name == 'sqlite':
        _downgrade_062_sqlite(migrate_engine, meta, stack)
    else:
        stack.c.parent_resource_name.drop()


def _downgrade_062_sqlite(migrate_engine, metadata, table):
    new_table = migrate_utils.clone_table(
        table.name + '__tmp__', table, metadata,
        ignorecols=['parent_resource_name'])
    migrate_utils.migrate_data(migrate_engine,
                               table,
                               new_table,
                               ['parent_resource_name'])
