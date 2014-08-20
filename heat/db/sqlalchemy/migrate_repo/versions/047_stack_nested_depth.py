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

import sqlalchemy


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    nested_depth = sqlalchemy.Column(
        'nested_depth', sqlalchemy.Integer(), default=0)
    nested_depth.create(stack)

    def get_stacks(owner_id):
        stmt = stack.select().where(stack.c.owner_id == owner_id)
        return migrate_engine.execute(stmt)

    def set_nested_depth(st, nested_depth):
        if st.backup:
            return
        values = {'nested_depth': nested_depth}
        update = stack.update().where(
            stack.c.id == st.id).values(values)
        migrate_engine.execute(update)

        # Recurse down the tree
        child_stacks = get_stacks(owner_id=st.id)
        child_nested_depth = nested_depth + 1
        for ch in child_stacks:
            set_nested_depth(ch, child_nested_depth)

    # Iterate over all top-level non nested stacks
    for st in get_stacks(owner_id=None):
        set_nested_depth(st, 0)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    stack = sqlalchemy.Table('stack', meta, autoload=True)
    stack.c.nested_depth.drop()
