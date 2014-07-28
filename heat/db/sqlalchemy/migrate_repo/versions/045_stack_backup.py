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


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    backup = sqlalchemy.Column('backup', sqlalchemy.Boolean(), default=False)
    backup.create(stack)

    # Set backup flag for backup stacks, which are the only ones named "foo*"
    not_deleted = None
    stmt = sqlalchemy.select([stack.c.id,
                              stack.c.name]).\
        where(stack.c.deleted_at == not_deleted)
    stacks = migrate_engine.execute(stmt)
    for s in stacks:
        if s.name.endswith('*'):
            values = {'backup': True}
            update = stack.update().where(
                stack.c.id == s.id).values(values)
            migrate_engine.execute(update)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    if migrate_engine.name == 'sqlite':
        _downgrade_045_sqlite(migrate_engine, meta, stack)
    else:
        stack.c.backup.drop()


def _downgrade_045_sqlite(migrate_engine, metadata, table):

    table_name = table.name

    constraints = [
        c.copy() for c in table.constraints
        if not isinstance(c, sqlalchemy.CheckConstraint)
    ]
    columns = [c.copy() for c in table.columns if c.name != "backup"]

    new_table = sqlalchemy.Table(table_name + "__tmp__", metadata,
                                 *(columns + constraints))
    new_table.create()

    migrate_data = """
        INSERT INTO stack__tmp__
            SELECT id, created_at, updated_at, name, raw_template_id,
                   user_creds_id, username, owner_id, status, status_reason,
                   parameters, timeout, tenant, disable_rollback, action,
                   deleted_at, stack_user_project_id
            FROM stack;"""

    migrate_engine.execute(migrate_data)

    table.drop()

    new_table.rename(table_name)
