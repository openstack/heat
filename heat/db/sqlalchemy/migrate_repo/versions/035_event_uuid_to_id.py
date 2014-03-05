
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
import itertools
import sqlalchemy

import migrate.changeset.constraint as constraint
from heat.openstack.common import timeutils


def upgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        upgrade_sqlite(migrate_engine)
        return

    meta = sqlalchemy.MetaData(bind=migrate_engine)

    event_table = sqlalchemy.Table('event', meta, autoload=True)
    event_uuid = sqlalchemy.Column('uuid', sqlalchemy.String(length=36),
                                   default=lambda: str(uuid.uuid4))
    event_table.create_column(event_uuid)

    if migrate_engine.name == 'postgresql':
        sequence = sqlalchemy.Sequence('evt')
        sqlalchemy.schema.CreateSequence(sequence,
                                         bind=migrate_engine).execute()
        event_id = sqlalchemy.Column('tmp_id', sqlalchemy.Integer,
                                     server_default=sqlalchemy.text(
                                         "nextval('evt')"))
    else:
        event_id = sqlalchemy.Column('tmp_id', sqlalchemy.Integer)
    event_table.create_column(event_id)

    fake_autoincrement = itertools.count(1)

    event_list = event_table.select().order_by(
        sqlalchemy.sql.expression.asc(event_table.c.created_at)).execute()
    for event in event_list:
        values = {'tmp_id': fake_autoincrement.next(), 'uuid': event.id}
        update = event_table.update().where(
            event_table.c.id == event.id).values(values)
        migrate_engine.execute(update)

    cons = constraint.UniqueConstraint('uuid', table=event_table)
    cons.create()

    event_table.c.id.drop()

    event_table.c.tmp_id.alter('id', sqlalchemy.Integer)

    cons = constraint.PrimaryKeyConstraint('tmp_id', table=event_table)
    cons.create()

    event_table.c.tmp_id.alter(sqlalchemy.Integer, autoincrement=True)


def upgrade_sqlite(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    #(pafuent) Here it isn't recommended to import the table from the models,
    #because in future migrations the model could change and this migration
    #could fail.
    #I know it is ugly but it's the only way that I found to 'freeze' the model
    #state for this migration.
    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    event_table = sqlalchemy.Table(
        'new_event', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey(stack_table.c.id),
                          nullable=False),
        sqlalchemy.Column('uuid', sqlalchemy.String(36),
                          default=lambda: str(uuid.uuid4()),
                          unique=True),
        sqlalchemy.Column('resource_action', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_status', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_name', sqlalchemy.String(255)),
        sqlalchemy.Column('physical_resource_id', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_type', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_properties', sqlalchemy.PickleType),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                          default=timeutils.utcnow),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime,
                          onupdate=timeutils.utcnow))
    event_table.create()

    prev_event_table = sqlalchemy.Table('event', meta, autoload=True)
    event_list = list(prev_event_table.select().order_by(
        sqlalchemy.sql.expression.asc(prev_event_table.c.created_at))
        .execute())
    for event in event_list:
        values = {
            'stack_id': event.stack_id,
            'uuid': event.id,
            'resource_action': event.resource_action,
            'resource_status': event.resource_status,
            'resource_name': event.resource_name,
            'physical_resource_id': event.physical_resource_id,
            'resource_status_reason': event.resource_status_reason,
            'resource_type': event.resource_type,
            'resource_properties': event.resource_properties}
        migrate_engine.execute(event_table.insert(values))

    prev_event_table.drop()
    event_table.rename('event')


def downgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        downgrade_sqlite(migrate_engine)
        return

    meta = sqlalchemy.MetaData(bind=migrate_engine)

    event_table = sqlalchemy.Table('event', meta, autoload=True)

    event_id = sqlalchemy.Column('tmp_id', sqlalchemy.String(length=36),
                                 default=lambda: str(uuid.uuid4))
    event_id.create(event_table)

    event_list = event_table.select().execute()
    for event in event_list:
        values = {'tmp_id': event.uuid}
        update = event_table.update().where(
            event_table.c.uuid == event.uuid).values(values)
        migrate_engine.execute(update)

    event_table.c.id.drop()
    event_table.c.uuid.drop()

    cons = constraint.PrimaryKeyConstraint('tmp_id', table=event_table)
    cons.create()

    event_table.c.tmp_id.alter('id', default=lambda: str(uuid.uuid4))


def downgrade_sqlite(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    #(pafuent) Here it isn't recommended to import the table from the models,
    #because in future migrations the model could change and this migration
    #could fail.
    #I know it is ugly but it's the only way that I found to 'freeze' the model
    #state for this migration.
    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    event_table = sqlalchemy.Table(
        'new_event', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          default=lambda: str(uuid.uuid4())),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey(stack_table.c.id),
                          nullable=False),
        sqlalchemy.Column('resource_action', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_status', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_name', sqlalchemy.String(255)),
        sqlalchemy.Column('physical_resource_id', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_type', sqlalchemy.String(255)),
        sqlalchemy.Column('resource_properties', sqlalchemy.PickleType),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                          default=timeutils.utcnow),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime,
                          onupdate=timeutils.utcnow))
    event_table.create()

    prev_event_table = sqlalchemy.Table('event', meta, autoload=True)
    event_list = prev_event_table.select().execute()
    for event in event_list:
        values = {
            'id': event.uuid,
            'stack_id': event.stack_id,
            'resource_action': event.resource_action,
            'resource_status': event.resource_status,
            'resource_name': event.resource_name,
            'physical_resource_id': event.physical_resource_id,
            'resource_status_reason': event.resource_status_reason,
            'resource_type': event.resource_type,
            'resource_properties': event.resource_properties}
        migrate_engine.execute(event_table.insert(values))

    prev_event_table.drop()
    event_table.rename('event')
