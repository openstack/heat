# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Initial revision

Revision ID: c6214ca60943
Revises:
Create Date: 2023-03-22 18:04:02.387269
"""

from alembic import op
import sqlalchemy as sa

import heat.db.types

# revision identifiers, used by Alembic.
revision = 'c6214ca60943'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'raw_template_files',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('files', heat.db.types.Json(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'resource_properties_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('data', heat.db.types.Json(), nullable=True),
        sa.Column('encrypted', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'service',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('engine_id', sa.String(length=36), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('hostname', sa.String(length=255), nullable=False),
        sa.Column('binary', sa.String(length=255), nullable=False),
        sa.Column('topic', sa.String(length=255), nullable=False),
        sa.Column('report_interval', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'software_config',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('group', sa.String(length=255), nullable=True),
        sa.Column('config', heat.db.types.Json(), nullable=True),
        sa.Column('tenant', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_index(
        op.f('ix_software_config_tenant'),
        'software_config',
        ['tenant'],
        unique=False,
    )
    op.create_table(
        'user_creds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('password', sa.String(length=255), nullable=True),
        sa.Column('region_name', sa.String(length=255), nullable=True),
        sa.Column('decrypt_method', sa.String(length=64), nullable=True),
        sa.Column('tenant', sa.String(length=1024), nullable=True),
        sa.Column('auth_url', sa.Text(), nullable=True),
        sa.Column('tenant_id', sa.String(length=256), nullable=True),
        sa.Column('trust_id', sa.String(length=255), nullable=True),
        sa.Column('trustor_user_id', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'raw_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('template', heat.db.types.Json(), nullable=True),
        sa.Column('files', heat.db.types.Json(), nullable=True),
        sa.Column(
            'environment', heat.db.types.Json(), nullable=True
        ),
        sa.Column('files_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['files_id'],
            ['raw_template_files.id'],
            name='raw_tmpl_files_fkey_ref',
        ),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'software_deployment',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('server_id', sa.String(length=36), nullable=False),
        sa.Column('config_id', sa.String(length=36), nullable=False),
        sa.Column(
            'input_values', heat.db.types.Json(), nullable=True
        ),
        sa.Column(
            'output_values', heat.db.types.Json(), nullable=True
        ),
        sa.Column('action', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=255), nullable=True),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('tenant', sa.String(length=64), nullable=False),
        sa.Column(
            'stack_user_project_id', sa.String(length=64), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ['config_id'],
            ['software_config.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_software_deployment_created_at',
        'software_deployment',
        ['created_at'],
        unique=False,
    )
    op.create_index(
        op.f('ix_software_deployment_server_id'),
        'software_deployment',
        ['server_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_software_deployment_tenant'),
        'software_deployment',
        ['tenant'],
        unique=False,
    )
    op.create_table(
        'stack',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('raw_template_id', sa.Integer(), nullable=False),
        sa.Column('prev_raw_template_id', sa.Integer(), nullable=True),
        sa.Column('user_creds_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=256), nullable=True),
        sa.Column('owner_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=255), nullable=True),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('timeout', sa.Integer(), nullable=True),
        sa.Column('tenant', sa.String(length=256), nullable=True),
        sa.Column('disable_rollback', sa.Boolean(), nullable=False),
        sa.Column(
            'stack_user_project_id', sa.String(length=64), nullable=True
        ),
        sa.Column('backup', sa.Boolean(), nullable=True),
        sa.Column('nested_depth', sa.Integer(), nullable=True),
        sa.Column('convergence', sa.Boolean(), nullable=True),
        sa.Column('current_traversal', sa.String(length=36), nullable=True),
        sa.Column(
            'current_deps', heat.db.types.Json(), nullable=True
        ),
        sa.Column(
            'parent_resource_name', sa.String(length=255), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ['prev_raw_template_id'],
            ['raw_template.id'],
        ),
        sa.ForeignKeyConstraint(
            ['raw_template_id'],
            ['raw_template.id'],
        ),
        sa.ForeignKeyConstraint(
            ['user_creds_id'],
            ['user_creds.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_stack_name', 'stack', ['name'], unique=False, mysql_length=255
    )
    op.create_index(
        'ix_stack_tenant', 'stack', ['tenant'], unique=False, mysql_length=255
    )
    op.create_index(
        op.f('ix_stack_owner_id'), 'stack', ['owner_id'], unique=False
    )
    op.create_table(
        'event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=True),
        sa.Column('stack_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('resource_action', sa.String(length=255), nullable=True),
        sa.Column('resource_status', sa.String(length=255), nullable=True),
        sa.Column('resource_name', sa.String(length=255), nullable=True),
        sa.Column(
            'physical_resource_id', sa.String(length=255), nullable=True
        ),
        sa.Column(
            'resource_status_reason', sa.String(length=255), nullable=True
        ),
        sa.Column('resource_type', sa.String(length=255), nullable=True),
        sa.Column('resource_properties', sa.PickleType(), nullable=True),
        sa.Column('rsrc_prop_data_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['rsrc_prop_data_id'],
            ['resource_properties_data.id'],
            name='ev_rsrc_prop_data_ref',
        ),
        sa.ForeignKeyConstraint(
            ['stack_id'],
            ['stack.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'resource',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=True),
        sa.Column('nova_instance', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('action', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=255), nullable=True),
        sa.Column('status_reason', sa.Text(), nullable=True),
        sa.Column('stack_id', sa.String(length=36), nullable=False),
        sa.Column(
            'rsrc_metadata', heat.db.types.Json(), nullable=True
        ),
        sa.Column(
            'properties_data', heat.db.types.Json(), nullable=True
        ),
        sa.Column('engine_id', sa.String(length=36), nullable=True),
        sa.Column('atomic_key', sa.Integer(), nullable=True),
        sa.Column('needed_by', heat.db.types.List(), nullable=True),
        sa.Column('requires', heat.db.types.List(), nullable=True),
        sa.Column('replaces', sa.Integer(), nullable=True),
        sa.Column('replaced_by', sa.Integer(), nullable=True),
        sa.Column('current_template_id', sa.Integer(), nullable=True),
        sa.Column('properties_data_encrypted', sa.Boolean(), nullable=True),
        sa.Column('root_stack_id', sa.String(length=36), nullable=True),
        sa.Column('rsrc_prop_data_id', sa.Integer(), nullable=True),
        sa.Column('attr_data_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['attr_data_id'],
            ['resource_properties_data.id'],
            name='rsrc_attr_data_ref',
        ),
        sa.ForeignKeyConstraint(
            ['current_template_id'],
            ['raw_template.id'],
        ),
        sa.ForeignKeyConstraint(
            ['rsrc_prop_data_id'],
            ['resource_properties_data.id'],
            name='rsrc_rsrc_prop_data_ref',
        ),
        sa.ForeignKeyConstraint(
            ['stack_id'],
            ['stack.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('uuid'),
        mysql_engine='InnoDB',
    )
    op.create_index(
        op.f('ix_resource_root_stack_id'),
        'resource',
        ['root_stack_id'],
        unique=False,
    )
    op.create_table(
        'snapshot',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('stack_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=255), nullable=True),
        sa.Column('status_reason', sa.String(length=255), nullable=True),
        sa.Column('data', heat.db.types.Json(), nullable=True),
        sa.Column('tenant', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ['stack_id'],
            ['stack.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_index(
        op.f('ix_snapshot_tenant'), 'snapshot', ['tenant'], unique=False
    )
    op.create_table(
        'stack_lock',
        sa.Column('stack_id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('engine_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ['stack_id'],
            ['stack.id'],
        ),
        sa.PrimaryKeyConstraint('stack_id'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'stack_tag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('tag', sa.Unicode(length=80), nullable=True),
        sa.Column('stack_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ['stack_id'],
            ['stack.id'],
        ),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
    op.create_table(
        'sync_point',
        sa.Column('entity_id', sa.String(length=36), nullable=False),
        sa.Column('traversal_id', sa.String(length=36), nullable=False),
        sa.Column('is_update', sa.Boolean(), nullable=False),
        sa.Column('atomic_key', sa.Integer(), nullable=False),
        sa.Column('stack_id', sa.String(length=36), nullable=False),
        sa.Column(
            'input_data', heat.db.types.Json(), nullable=True
        ),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ['stack_id'],
            ['stack.id'],
        ),
        sa.PrimaryKeyConstraint('entity_id', 'traversal_id', 'is_update'),
    )
    op.create_table(
        'resource_data',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('key', sa.String(length=255), nullable=True),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('redact', sa.Boolean(), nullable=True),
        sa.Column('decrypt_method', sa.String(length=64), nullable=True),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['resource_id'],
            ['resource.id'],
            name='fk_resource_id',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
    )
