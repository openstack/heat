from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    stack = Table('stack', meta, autoload=True)
    watch_rule = Table('watch_rule', meta, autoload=True)

    Column('stack_id', String(length=36), ForeignKey("stack.id"),
           nullable=False).create(watch_rule)

    watch_rule.c.stack_name.drop()


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    watch_rule = Table('watch_rule', meta, autoload=True)

    watch_rule.c.stack_id.drop()
    Column('stack_name', String(length=255), convert_unicode=False,
           assert_unicode=None, unicode_error=None,
           _warn_on_bytestring=False).create(watch_rule)
