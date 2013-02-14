from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    stack = Table('stack', meta, autoload=True)

    # Note hard-coded default 60 (minutes) here from the value in the
    # engine, means we can upgrade and populate existing rows
    try:
        col = Column('disable_rollback', Boolean, nullable=False, default=True)
        col.create(stack, populate_default=True)
    except Exception as ex:
        print "Caught exception adding disable_rollback column %s" % ex
        # *Hack-alert* Sqlite in the unit tests can't handle the above
        # approach to nullable=False, so retry with nullable=True
        Column('disable_rollback', Boolean, nullable=True,
               default=60).create(stack)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    stack = Table('stack', meta, autoload=True)

    stack.c.disable_rollback.drop()
