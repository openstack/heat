from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    event = Table('event', meta, autoload=True)

    Column('logical_resource_id', String(255)).create(event)
    Column('physical_resource_id', String(255)).create(event)
    Column('resource_status_reason', String(255)).create(event)
    Column('resource_type', String(255)).create(event)
    Column('resource_properties', PickleType).create(event)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    event = Table('event', meta, autoload=True)

    event.c.logical_resource_id.drop()
    event.c.physical_resource_id.drop()
    event.c.resource_status_reason.drop()
    event.c.resource_type.drop()
    event.c.resource_properties.drop()
