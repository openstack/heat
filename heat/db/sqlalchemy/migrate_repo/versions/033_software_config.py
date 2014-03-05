
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

from heat.db.sqlalchemy.types import Json
from heat.db.sqlalchemy.types import LongText


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    software_config = sqlalchemy.Table(
        'software_config', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('name', sqlalchemy.String(255),
                          nullable=True),
        sqlalchemy.Column('group', sqlalchemy.String(255)),
        sqlalchemy.Column('config', LongText),
        sqlalchemy.Column('io', Json),
        sqlalchemy.Column('tenant', sqlalchemy.String(256),
                          nullable=False,
                          index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    software_config.create()

    software_deployment = sqlalchemy.Table(
        'software_deployment', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                          index=True),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('server_id', sqlalchemy.String(36),
                          nullable=False,
                          index=True),
        sqlalchemy.Column('config_id',
                          sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('software_config.id'),
                          nullable=False),
        sqlalchemy.Column('input_values', Json),
        sqlalchemy.Column('output_values', Json),
        sqlalchemy.Column('signal_id', sqlalchemy.String(1024)),
        sqlalchemy.Column('action', sqlalchemy.String(255)),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('tenant', sqlalchemy.String(256),
                          nullable=False,
                          index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    software_deployment.create()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    software_deployment = sqlalchemy.Table(
        'software_deployment', meta, autoload=True)
    software_deployment.drop()
    software_config = sqlalchemy.Table(
        'software_config', meta, autoload=True)
    software_config.drop()
