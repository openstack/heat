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
    stack.c.backup.drop()
