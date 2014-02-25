
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
    sqlalchemy.Column('deleted_at', sqlalchemy.DateTime).create(stack)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    event = sqlalchemy.Table('event', meta, autoload=True)
    user_creds = sqlalchemy.Table('user_creds', meta, autoload=True)
    raw_template = sqlalchemy.Table('raw_template', meta, autoload=True)

    # Remove soft deleted data
    not_deleted = None
    stmt = sqlalchemy.select([stack.c.id,
                              stack.c.raw_template_id,
                              stack.c.user_creds_id]).\
        where(stack.c.deleted_at != not_deleted)
    deleted_stacks = migrate_engine.execute(stmt)
    for s in deleted_stacks:
        event_del = event.delete().where(event.c.stack_id == s[0])
        migrate_engine.execute(event_del)
        stack_del = stack.delete().where(stack.c.id == s[0])
        migrate_engine.execute(stack_del)
        raw_template_del = raw_template.delete().\
            where(raw_template.c.id == s[1])
        migrate_engine.execute(raw_template_del)
        user_creds_del = user_creds.delete().where(user_creds.c.id == s[2])
        migrate_engine.execute(user_creds_del)

    stack.c.deleted_at.drop()
