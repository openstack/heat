
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

import uuid

import sqlalchemy


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    resource = sqlalchemy.Table('resource', meta, autoload=True)

    resource.c.id.alter(sqlalchemy.String(36), primary_key=True,
                        default=lambda: str(uuid.uuid4()))


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    resource = sqlalchemy.Table('resource', meta, autoload=True)

    try:
        resource.c.id.alter(sqlalchemy.Integer, primary_key=True)
    except:
        #XXX: since there is no way to downgrade just passing
        pass
