from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    resource = Table('resource', meta, autoload=True)
    Column('rsrc_metadata', Text()).create(resource)

    stack = Table('stack', meta, autoload=True)
    Column('status', String(length=255,
                            convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None,
                            _warn_on_bytestring=False)).create(stack)
    Column('status_reason', String(length=255,
                                   convert_unicode=False,
                                   assert_unicode=None,
                                   unicode_error=None,
                                   _warn_on_bytestring=False)).create(stack)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    resource = Table('resource', meta, autoload=True)
    resource.c.rsrc_metadata.drop()

    stack = Table('stack', meta, autoload=True)
    stack.c.status.drop()
    stack.c.status_reason.drop()
