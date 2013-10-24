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

    resource_data = sqlalchemy.Table(
        'resource_data', meta,
        sqlalchemy.Column('id',
                          sqlalchemy.Integer,
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('key', sqlalchemy.String(255)),
        sqlalchemy.Column('value', sqlalchemy.Text),
        sqlalchemy.Column('redact', sqlalchemy.Boolean),
        sqlalchemy.Column('resource_id',
                          sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('resource.id'),
                          nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    sqlalchemy.Table('resource', meta, autoload=True)
    resource_data.create()


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    resource_data = sqlalchemy.Table('resource_data', meta, autoload=True)
    resource_data.drop()
