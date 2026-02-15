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

"""make snapshot state aware

Revision ID: 97b2a986f922
Revises: 88be64598c0f
Create Date: 2026-02-15 14:09:59.134120
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '97b2a986f922'
down_revision = '88be64598c0f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('snapshot',
                  sa.Column('action', sa.String(255), nullable=True))

    connection = op.get_bind()
    snapshot_table = sa.Table('snapshot', sa.MetaData(),
                              autoload_with=connection)
    op.execute(
        snapshot_table.update().where(
            snapshot_table.c.action.is_(None)
        ).values({
            'action': 'CREATE'
        })
    )


def downgrade():
    op.drop_column('snapshot', 'action')
