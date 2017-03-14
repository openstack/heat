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

import uuid

import sqlalchemy

from heat.db.sqlalchemy import types


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    raw_template = sqlalchemy.Table(
        'raw_template', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('template', types.LongText),
        sqlalchemy.Column('files', types.Json),
        sqlalchemy.Column('environment', types.Json),

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
        sqlalchemy.Column('region_name', sqlalchemy.String(length=255)),
        sqlalchemy.Column('decrypt_method', sqlalchemy.String(length=64)),
        sqlalchemy.Column('tenant', sqlalchemy.String(1024)),
        sqlalchemy.Column('auth_url', sqlalchemy.Text),
        sqlalchemy.Column('tenant_id', sqlalchemy.String(256)),
        sqlalchemy.Column('trust_id', sqlalchemy.String(255)),
        sqlalchemy.Column('trustor_user_id', sqlalchemy.String(64)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    stack = sqlalchemy.Table(
        'stack', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          primary_key=True, nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('deleted_at', sqlalchemy.DateTime),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('raw_template_id',
                          sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('raw_template.id'),
                          nullable=False),
        sqlalchemy.Column('prev_raw_template_id',
                          sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('raw_template.id')),
        sqlalchemy.Column('user_creds_id', sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('user_creds.id')),
        sqlalchemy.Column('username', sqlalchemy.String(256)),
        sqlalchemy.Column('owner_id', sqlalchemy.String(36)),
        sqlalchemy.Column('action', sqlalchemy.String(255)),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', types.LongText),
        sqlalchemy.Column('timeout', sqlalchemy.Integer),
        sqlalchemy.Column('tenant', sqlalchemy.String(256)),
        sqlalchemy.Column('disable_rollback', sqlalchemy.Boolean,
                          nullable=False),
        sqlalchemy.Column('stack_user_project_id',
                          sqlalchemy.String(length=64)),
        sqlalchemy.Column('backup', sqlalchemy.Boolean, default=False),
        sqlalchemy.Column('nested_depth', sqlalchemy.Integer, default=0),
        sqlalchemy.Column('convergence', sqlalchemy.Boolean, default=False),
        sqlalchemy.Column('current_traversal', sqlalchemy.String(36)),
        sqlalchemy.Column('current_deps', types.Json),
        sqlalchemy.Column('parent_resource_name', sqlalchemy.String(255)),
        sqlalchemy.Index('ix_stack_name', 'name', mysql_length=255),
        sqlalchemy.Index('ix_stack_tenant', 'tenant', mysql_length=255),
        sqlalchemy.Index('ix_stack_owner_id', 'owner_id', mysql_length=36),

        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    resource = sqlalchemy.Table(
        'resource', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('uuid', sqlalchemy.String(36), unique=True,
                          default=lambda: str(uuid.uuid4())),
        sqlalchemy.Column('nova_instance', sqlalchemy.String(255)),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('action', sqlalchemy.String(255)),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', types.LongText),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'), nullable=False),
        sqlalchemy.Column('rsrc_metadata', types.LongText),
        sqlalchemy.Column('properties_data', types.Json),
        sqlalchemy.Column('engine_id', sqlalchemy.String(length=36)),
        sqlalchemy.Column('atomic_key', sqlalchemy.Integer),
        sqlalchemy.Column('needed_by', types.List),
        sqlalchemy.Column('requires', types.List),
        sqlalchemy.Column('replaces', sqlalchemy.Integer),
        sqlalchemy.Column('replaced_by', sqlalchemy.Integer),
        sqlalchemy.Column('current_template_id', sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('raw_template.id')),
        sqlalchemy.Column('properties_data_encrypted',
                          sqlalchemy.Boolean,
                          default=False),
        sqlalchemy.Column('root_stack_id', sqlalchemy.String(36)),
        sqlalchemy.Index('ix_resource_root_stack_id',
                         'root_stack_id',
                         mysql_length=36),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    resource_data = sqlalchemy.Table(
        'resource_data', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('key', sqlalchemy.String(255)),
        sqlalchemy.Column('value', sqlalchemy.Text),
        sqlalchemy.Column('redact', sqlalchemy.Boolean),
        sqlalchemy.Column('decrypt_method', sqlalchemy.String(length=64)),
        sqlalchemy.Column('resource_id',
                          sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('resource.id'),
                          nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    event = sqlalchemy.Table(
        'event', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True,
                          nullable=False),
        sqlalchemy.Column('uuid', sqlalchemy.String(36),
                          default=lambda: str(uuid.uuid4()), unique=True),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'), nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('resource_action', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_status', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_name', sqlalchemy.String(255)),
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
        sqlalchemy.Column('rule', types.LongText),
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
        sqlalchemy.Column('data', types.LongText),
        sqlalchemy.Column('watch_rule_id', sqlalchemy.Integer,
                          sqlalchemy.ForeignKey('watch_rule.id'),
                          nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    stack_lock = sqlalchemy.Table(
        'stack_lock', meta,
        sqlalchemy.Column('stack_id', sqlalchemy.String(length=36),
                          sqlalchemy.ForeignKey('stack.id'),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('engine_id', sqlalchemy.String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    software_config = sqlalchemy.Table(
        'software_config', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('group', sqlalchemy.String(255)),
        sqlalchemy.Column('config', types.LongText),
        sqlalchemy.Column('tenant', sqlalchemy.String(64),
                          nullable=False,
                          index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

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
        sqlalchemy.Column('input_values', types.Json),
        sqlalchemy.Column('output_values', types.Json),
        sqlalchemy.Column('action', sqlalchemy.String(255)),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', types.LongText),
        sqlalchemy.Column('tenant', sqlalchemy.String(64),
                          nullable=False,
                          index=True),
        sqlalchemy.Column('stack_user_project_id',
                          sqlalchemy.String(length=64)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    snapshot = sqlalchemy.Table(
        'snapshot', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('stack_id',
                          sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'),
                          nullable=False),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('data', types.Json),
        sqlalchemy.Column('tenant', sqlalchemy.String(64),
                          nullable=False,
                          index=True),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    service = sqlalchemy.Table(
        'service', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36), primary_key=True,
                          default=lambda: str(uuid.uuid4())),
        sqlalchemy.Column('engine_id', sqlalchemy.String(36), nullable=False),
        sqlalchemy.Column('host', sqlalchemy.String(255), nullable=False),
        sqlalchemy.Column('hostname', sqlalchemy.String(255), nullable=False),
        sqlalchemy.Column('binary', sqlalchemy.String(255), nullable=False),
        sqlalchemy.Column('topic', sqlalchemy.String(255), nullable=False),
        sqlalchemy.Column('report_interval', sqlalchemy.Integer,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('deleted_at', sqlalchemy.DateTime),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    stack_tag = sqlalchemy.Table(
        'stack_tag', meta,
        sqlalchemy.Column('id',
                          sqlalchemy.Integer,
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('tag', sqlalchemy.Unicode(80)),
        sqlalchemy.Column('stack_id',
                          sqlalchemy.String(36),
                          sqlalchemy.ForeignKey('stack.id'),
                          nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sync_point = sqlalchemy.Table(
        'sync_point', meta,
        sqlalchemy.Column('entity_id', sqlalchemy.String(36)),
        sqlalchemy.Column('traversal_id', sqlalchemy.String(36)),
        sqlalchemy.Column('is_update', sqlalchemy.Boolean),
        sqlalchemy.Column('atomic_key', sqlalchemy.Integer,
                          nullable=False),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          nullable=False),
        sqlalchemy.Column('input_data', types.Json),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),

        sqlalchemy.PrimaryKeyConstraint('entity_id',
                                        'traversal_id',
                                        'is_update'),
        sqlalchemy.ForeignKeyConstraint(['stack_id'], ['stack.id'],
                                        name='fk_stack_id'),

        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    tables = (
        raw_template,
        user_creds,
        stack,
        resource,
        resource_data,
        event,
        watch_rule,
        watch_data,
        stack_lock,
        software_config,
        software_deployment,
        snapshot,
        service,
        stack_tag,
        sync_point,
    )

    for index, table in enumerate(tables):
        try:
            table.create()
        except Exception:
            # If an error occurs, drop all tables created so far to return
            # to the previously existing state.
            meta.drop_all(tables=tables[:index])
            raise
