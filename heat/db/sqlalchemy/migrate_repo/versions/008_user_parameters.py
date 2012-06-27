from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    stack = Table('stack', meta, autoload=True)
    Column('parameters', Text()).create(stack)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    stack = Table('stack', meta, autoload=True)
    stack.c.parameters.drop()
