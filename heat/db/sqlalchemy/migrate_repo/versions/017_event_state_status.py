
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

    event = sqlalchemy.Table('event', meta, autoload=True)
    # Currently there is a 'name' column which really holds the
    # resource status, so rename it and add a separate action column
    # action is e.g "CREATE" and status is e.g "IN_PROGRESS"
    event.c.name.alter(name='resource_status')
    sqlalchemy.Column('resource_action', sqlalchemy.String(255)).create(event)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    event = sqlalchemy.Table('event', meta, autoload=True)
    event.c.resource_status.alter(name='name')
    event.c.resource_action.drop()
