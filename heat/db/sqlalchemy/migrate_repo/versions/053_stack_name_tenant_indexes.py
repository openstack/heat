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

    name_index = sqlalchemy.Index('ix_stack_name', stack.c.name,
                                  mysql_length=255)
    name_index.create(migrate_engine)

    tenant_index = sqlalchemy.Index('ix_stack_tenant', stack.c.tenant,
                                    mysql_length=255)
    tenant_index.create(migrate_engine)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    stack = sqlalchemy.Table('stack', meta, autoload=True)

    name_index = sqlalchemy.Index('ix_stack_name', stack.c.name,
                                  mysql_length=255)
    name_index.drop(migrate_engine)

    tenant_index = sqlalchemy.Index('ix_stack_tenant', stack.c.tenant,
                                    mysql_length=255)
    tenant_index.drop(migrate_engine)
