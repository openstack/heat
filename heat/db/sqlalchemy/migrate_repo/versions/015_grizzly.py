# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    raw_template = Table(
        'raw_template', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('template', Text),
    )

    user_creds = Table(
        'user_creds', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('username', String(255)),
        Column('password', String(255)),
        Column('service_user', String(255)),
        Column('service_password', String(255)),
        Column('tenant', String(1024)),
        Column('auth_url', Text),
        Column('aws_auth_url', Text),
        Column('tenant_id', String(256)),
        Column('aws_creds', Text),
    )

    stack = Table(
        'stack', meta,
        Column('id', String(36), primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('name', String(255)),
        Column('raw_template_id', Integer, ForeignKey('raw_template.id'),
               nullable=False),
        Column('user_creds_id', Integer, ForeignKey('user_creds.id'),
               nullable=False),
        Column('username', String(256)),
        Column('owner_id', String(36)),
        Column('status', String(255)),
        Column('status_reason', String(255)),
        Column('parameters', Text),
        Column('timeout', Integer, nullable=False),
        Column('tenant', String(256)),
        Column('disable_rollback', Boolean, nullable=False),
    )

    resource = Table(
        'resource', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('nova_instance', String(255)),
        Column('name', String(255)),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('state', String(255)),
        Column('state_description', String(255)),
        Column('stack_id', String(36), ForeignKey('stack.id'),
               nullable=False),
        Column('rsrc_metadata', Text),
    )

    event = Table(
        'event', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('stack_id', String(36), ForeignKey('stack.id'),
               nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('name', String(255)),
        Column('logical_resource_id', String(255)),
        Column('physical_resource_id', String(255)),
        Column('resource_status_reason', String(255)),
        Column('resource_type', String(255)),
        Column('resource_properties', PickleType),
    )

    watch_rule = Table(
        'watch_rule', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('name', String(255)),
        Column('state', String(255)),
        Column('rule', Text),
        Column('last_evaluated', DateTime),
        Column('stack_id', String(36), ForeignKey('stack.id'),
               nullable=False),
    )

    watch_data = Table(
        'watch_data', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('data', Text),
        Column('watch_rule_id', Integer, ForeignKey('watch_rule.id'),
               nullable=False),
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
    raise Exception('Database downgrade not supported - would drop all tables')
