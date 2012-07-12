from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    stack = Table('stack', meta, autoload=True)

    # Note hard-coded default 60 (minutes) here from the value in the
    # engine, means we can upgrade and populate existing rows
    try:
        col = Column('timeout', Integer, nullable=False, default=60)
        col.create(stack, populate_default=True)
    except Exception as ex:
        print "Caught exception adding timeout column to stacks %s" % ex
        # *Hack-alert* Sqlite in the unit tests can't handle the above
        # approach to nullable=False, so retry with nullable=True
        Column('timeout', Integer, nullable=True, default=60).create(stack)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    stack = Table('stack', meta, autoload=True)

    stack.c.timeout.drop()
