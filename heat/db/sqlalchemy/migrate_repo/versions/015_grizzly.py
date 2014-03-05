
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

    raw_template = sqlalchemy.Table(
        'raw_template', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('template', sqlalchemy.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    user_creds = sqlalchemy.Table(
        'user_creds', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer,
                          primary_key=True, nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('username', sqlalchemy.String(255)),
        sqlalchemy.Column('password', sqlalchemy.String(255)),
        sqlalchemy.Column('service_user', sqlalchemy.String(255)),
        sqlalchemy.Column('service_password', sqlalchemy.String(255)),
        sqlalchemy.Column('tenant', sqlalchemy.String(1024)),
        sqlalchemy.Column('auth_url', sqlalchemy.Text),
        sqlalchemy.Column('aws_auth_url', sqlalchemy.Text),
        sqlalchemy.Column('tenant_id', sqlalchemy.String(256)),
        sqlalchemy.Column('aws_creds', sqlalchemy.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    stack = sqlalchemy.Table(
        'stack', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          primary_key=True, nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('raw_template_id',
                          sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('raw_template.id'),
                          nullable=False),
        sqlalchemy.Column('user_creds_id', sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('user_creds.id'),
                          nullable=False),
        sqlalchemy.Column('username', sqlalchemy.String(256)),
        sqlalchemy.Column('owner_id', sqlalchemy.String(36)),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('parameters', sqlalchemy.Text),
        sqlalchemy.Column('timeout', sqlalchemy.Integer, nullable=False),
        sqlalchemy.Column('tenant', sqlalchemy.String(256)),
        sqlalchemy.Column('disable_rollback', sqlalchemy.Boolean,
                          nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    resource = sqlalchemy.Table(
        'resource', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('nova_instance', sqlalchemy.String(255)),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('state', sqlalchemy.String(255)),
        sqlalchemy.Column('state_description', sqlalchemy.String(255)),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'), nullable=False),
        sqlalchemy.Column('rsrc_metadata', sqlalchemy.Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    event = sqlalchemy.Table(
        'event', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer,
                          primary_key=True, nullable=False),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'), nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('logical_resource_id', sqlalchemy.String(255)),
        sqlalchemy.Column('physical_resource_id', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_type', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_properties', sqlalchemy.PickleType),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    watch_rule = sqlalchemy.Table(
        'watch_rule', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('state', sqlalchemy.String(255)),
        sqlalchemy.Column('rule', sqlalchemy.Text),
        sqlalchemy.Column('last_evaluated', sqlalchemy.DateTime),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    watch_data = sqlalchemy.Table(
        'watch_data', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('data', sqlalchemy.Text),
        sqlalchemy.Column('watch_rule_id', sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('watch_rule.id'),
                          nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    tables = (
        raw_template,
        user_creds,
        stack,
        resource,
        event,
        watch_rule,
        watch_data,
    )

    for index, table in enumerate(tables):
        try:
            table.create()
        except:
            # If an error occurs, drop all tables created so far to return
            # to the previously existing state.
            meta.drop_all(tables=tables[:index])
            raise


def downgrade(migrate_engine):
    raise NotImplementedError('Database downgrade not supported - '
                              'would drop all tables')
