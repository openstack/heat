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
from heat.db.sqlalchemy import utils as migrate_utils

from migrate import ForeignKeyConstraint


def upgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        _upgrade_sqlite(migrate_engine)
        return

    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)

    prev_raw_template_id = sqlalchemy.Column('prev_raw_template_id',
                                             sqlalchemy.Integer)
    current_traversal = sqlalchemy.Column('current_traversal',
                                          sqlalchemy.String(36))
    current_deps = sqlalchemy.Column('current_deps', heat_db_types.Json)
    prev_raw_template_id.create(stack)
    current_traversal.create(stack)
    current_deps.create(stack)

    raw_template = sqlalchemy.Table('raw_template', meta, autoload=True)
    fkey = ForeignKeyConstraint(columns=[stack.c.prev_raw_template_id],
                                refcolumns=[raw_template.c.id],
                                name='prev_raw_template_ref')
    fkey.create()


def _upgrade_sqlite(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    stack = sqlalchemy.Table('stack', meta, autoload=True)
    table_name = stack.name

    newcols = [
        sqlalchemy.Column('prev_raw_template_id', sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('raw_template.id',
                                                name='prev_raw_template_ref')),
        sqlalchemy.Column('current_traversal', sqlalchemy.String(36)),
        sqlalchemy.Column('current_deps', heat_db_types.Json),
    ]

    new_stack = migrate_utils.clone_table(table_name + '__tmp__', stack,
                                          meta, newcols=newcols)

    # migrate stacks into new table
    stacks = list(stack.select().order_by(
        sqlalchemy.sql.expression.asc(stack.c.created_at))
        .execute())
    colnames = [c.name for c in stack.columns]
    for s in stacks:
        values = dict(zip(colnames,
                          map(lambda colname: getattr(s, colname),
                              colnames)))
        migrate_engine.execute(new_stack.insert(values))

    # Drop old tables and rename new ones
    stack.drop()
    new_stack.rename('stack')

    # add the indexes back
    _add_indexes(migrate_engine, new_stack)


def _add_indexes(migrate_engine, stack):
    name_index = sqlalchemy.Index('ix_stack_name',
                                  stack.c.name,
                                  mysql_length=255)
    tenant_index = sqlalchemy.Index('ix_stack_tenant',
                                    stack.c.tenant,
                                    mysql_length=255)
    name_index.create(migrate_engine)
    tenant_index.create(migrate_engine)
