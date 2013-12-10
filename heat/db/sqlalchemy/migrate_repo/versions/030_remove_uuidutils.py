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
import uuid


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    stack.c.id.alter(type=sqlalchemy.String(36), primary_key=True,
                     default=lambda: str(uuid.uuid4()))

    event = sqlalchemy.Table('event', meta, autoload=True)
    event.c.id.alter(type=sqlalchemy.String(36), primary_key=True,
                     default=lambda: str(uuid.uuid4()))

    resource = sqlalchemy.Table('resource', meta, autoload=True)
    resource.c.id.alter(type=sqlalchemy.String(36), primary_key=True,
                        default=lambda: str(uuid.uuid4()))


def downgrade(migrate_engine):
    # since uuid.uuid4() works so no need to do downgrade
    pass
