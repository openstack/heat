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

import migrate
import sqlalchemy

from heat.db.sqlalchemy import types as heat_db_types
from heat.db.sqlalchemy import utils as migrate_utils


def upgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        upgrade_sqlite(migrate_engine)
        return

    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    tmpl_table = sqlalchemy.Table('raw_template', meta, autoload=True)
    environment = sqlalchemy.Column('environment', heat_db_types.Json)
    environment.create(tmpl_table)
    predecessor = sqlalchemy.Column('predecessor', sqlalchemy.Integer)
    predecessor.create(tmpl_table)

    fkey = migrate.ForeignKeyConstraint(
        columns=[tmpl_table.c.predecessor],
        refcolumns=[tmpl_table.c.id],
        name='predecessor_fkey_ref')
    fkey.create()

    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    update_query = tmpl_table.update().values(
        environment=sqlalchemy.select([stack_table.c.parameters]).
        where(sqlalchemy.and_(stack_table.c.raw_template_id == tmpl_table.c.id,
                              stack_table.c.deleted_at.is_(None))).as_scalar())
    migrate_engine.execute(update_query)

    stack_table.c.parameters.drop()


def upgrade_sqlite(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    tmpl_table = sqlalchemy.Table('raw_template', meta, autoload=True)
    newcols = [
        sqlalchemy.Column('environment', heat_db_types.Json),
        sqlalchemy.Column('predecessor', sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('raw_template.id'))]
    new_template = migrate_utils.clone_table('new_raw_template',
                                             tmpl_table,
                                             meta, newcols=newcols)

    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    ignorecols = [stack_table.c.parameters.name]
    new_stack = migrate_utils.clone_table('new_stack', stack_table,
                                          meta, ignorecols=ignorecols)

    # migrate parameters to environment
    templates = list(tmpl_table.select().order_by(
        sqlalchemy.sql.expression.asc(tmpl_table.c.created_at))
        .execute())
    stacks = list(stack_table.select().order_by(
        sqlalchemy.sql.expression.asc(stack_table.c.created_at))
        .execute())

    stack_parameters = {}
    for s in stacks:
        stack_parameters[s.raw_template_id] = (s.parameters, s.deleted_at)

    colnames = [c.name for c in tmpl_table.columns]
    for template in templates:
        values = dict(zip(colnames,
                          map(lambda colname: getattr(template, colname),
                              colnames)))
        params, del_at = stack_parameters.get(values['id'], (None, None))
        if params is not None and del_at is None:
            values['environment'] = params
        migrate_engine.execute(new_template.insert(values))

    # migrate stacks to new table
    migrate_utils.migrate_data(migrate_engine,
                               stack_table,
                               new_stack,
                               skip_columns=['parameters'])

    # Drop old tables and rename new ones
    tmpl_table.drop()

    # add the indexes back to new table
    _add_indexes(migrate_engine, new_stack)
    new_template.rename('raw_template')


def downgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        downgrade_sqlite(migrate_engine)
        return

    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    parameters = sqlalchemy.Column('parameters', heat_db_types.Json)
    parameters.create(stack_table)

    tmpl_table = sqlalchemy.Table('raw_template', meta, autoload=True)
    update_query = stack_table.update().values(
        parameters=sqlalchemy.select([tmpl_table.c.environment]).
        where(stack_table.c.raw_template_id == tmpl_table.c.id).
        as_scalar())
    migrate_engine.execute(update_query)

    tmpl_table.c.environment.drop()

    fkey = migrate.ForeignKeyConstraint(
        columns=[tmpl_table.c.predecessor],
        refcolumns=[tmpl_table.c.id],
        name='predecessor_fkey_ref')
    fkey.drop()
    tmpl_table.c.predecessor.drop()


def downgrade_sqlite(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    newcols = [sqlalchemy.Column('parameters', heat_db_types.Json)]
    new_stack = migrate_utils.clone_table('new_stack', stack_table,
                                          meta, newcols=newcols)

    tmpl_table = sqlalchemy.Table('raw_template', meta, autoload=True)
    ignorecols = [tmpl_table.c.environment.name, tmpl_table.c.predecessor.name]
    new_template = migrate_utils.clone_table('new_raw_template', tmpl_table,
                                             meta, ignorecols=ignorecols)

    # migrate stack data to new table
    stacks = list(stack_table.select().order_by(
        sqlalchemy.sql.expression.asc(stack_table.c.created_at))
        .execute())
    colnames = [c.name for c in stack_table.columns]
    for stack in stacks:
        values = dict(zip(colnames,
                          map(lambda colname: getattr(stack, colname),
                              colnames)))
        migrate_engine.execute(new_stack.insert(values))

    update_query = new_stack.update().values(
        parameters=sqlalchemy.select([tmpl_table.c.environment]).
        where(new_stack.c.raw_template_id == tmpl_table.c.id).
        as_scalar())
    migrate_engine.execute(update_query)

    # migrate template data to new table
    migrate_utils.migrate_data(migrate_engine,
                               tmpl_table,
                               new_template,
                               skip_columns=['environment', 'predecessor'])

    stack_table.drop()
    new_stack.rename('stack')

    # add the indexes back to new table
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
