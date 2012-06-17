from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    # This was unused
    resource = Table('resource', meta, autoload=True)
    resource.c.depends_on.drop()

    stack = Table('stack', meta, autoload=True)
    Column('owner_id', Integer, nullable=True).create(stack)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    resource = Table('resource', meta, autoload=True)
    Column('depends_on', Integer).create(resource)

    stack = Table('stack', meta, autoload=True)
    stack.c.owner_id.drop()
