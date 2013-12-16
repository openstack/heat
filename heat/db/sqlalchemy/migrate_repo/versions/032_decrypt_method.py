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

    for table in ('user_creds', 'resource_data'):
        table = sqlalchemy.Table(table, meta, autoload=True)
        method = sqlalchemy.Column('decrypt_method',
                                   sqlalchemy.String(length=64),
                                   default='heat_decrypt')
        method.create(table)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    for table in ('user_creds', 'resource_data'):
        table = sqlalchemy.Table(table, meta, autoload=True)
        table.c.decrypt_method.drop()
