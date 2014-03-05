
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

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    # Align the current state/state_description with the
    # action/status now used in the event table
    action = sqlalchemy.Column('action',
                               sqlalchemy.String(length=255))
    action.create(resource)
    resource.c.state.alter(name='status')
    resource.c.state_description.alter(name='status_reason')


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    resource.c.action.drop()
    resource.c.status.alter(name='state')
    resource.c.status_reason.alter(name='state_description')
