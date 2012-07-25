from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    stack = Table('stack', meta, autoload=True)

    Column('tenant', String(length=256, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None,
                            _warn_on_bytestring=False)).create(stack)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    stack = Table('stack', meta, autoload=True)
    stack.c.tenant.drop()
