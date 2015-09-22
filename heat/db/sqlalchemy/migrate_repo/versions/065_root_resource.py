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

    res_table = sqlalchemy.Table('resource', meta, autoload=True)
    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    root_stack_id = sqlalchemy.Column('root_stack_id',
                                      sqlalchemy.String(36))

    root_stack_id.create(res_table)
    root_stack_idx = sqlalchemy.Index('ix_resource_root_stack_id',
                                      res_table.c.root_stack_id,
                                      mysql_length=36)
    root_stack_idx.create(migrate_engine)

    # build stack->owner relationship for all stacks
    stmt = sqlalchemy.select([stack_table.c.id, stack_table.c.owner_id])
    stacks = migrate_engine.execute(stmt)
    parent_stacks = dict([(s.id, s.owner_id) for s in stacks])

    def root_for_stack(stack_id):
        owner_id = parent_stacks.get(stack_id)
        if owner_id:
            return root_for_stack(owner_id)
        return stack_id

    # for each stack, update the resources with the root_stack_id
    for stack_id, owner_id in parent_stacks.items():
        root_id = root_for_stack(stack_id)
        values = {'root_stack_id': root_id}
        update = res_table.update().where(
            res_table.c.stack_id == stack_id).values(values)
        migrate_engine.execute(update)
