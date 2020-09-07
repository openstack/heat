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

"""Add resource_snapshot table

Revision ID: 88be64598c0f
Revises: d2db381e3324
Create Date: 2025-01-24

"""
from alembic import op
import sqlalchemy as sa

from heat.db import types

# revision identifiers, used by Alembic.
revision = '88be64598c0f'
down_revision = 'd2db381e3324'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'resource_snapshot',
        sa.Column('id', sa.String(36), primary_key=True, nullable=False),
        sa.Column('snapshot_id', sa.String(36),
                  sa.ForeignKey('snapshot.id'), nullable=False),
        sa.Column('resource_name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('data', types.Json),
        sa.Index('ix_resource_snapshot_snapshot_id', 'snapshot_id'),
        mysql_engine='InnoDB',
    )


def downgrade():
    op.drop_table('resource_snapshot')
