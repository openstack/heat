from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    watch_rule = Table(
        'watch_rule', meta,
        Column('id', Integer, primary_key=True),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('stack_name', String(length=255, convert_unicode=False,
                              assert_unicode=None,
                              unicode_error=None, _warn_on_bytestring=False)),
        Column('name', String(length=255, convert_unicode=False,
                              assert_unicode=None,
                              unicode_error=None, _warn_on_bytestring=False)),
        Column('state', String(length=255, convert_unicode=False,
                               assert_unicode=None,
                               unicode_error=None, _warn_on_bytestring=False)),
        Column('rule', Text()),
        Column('last_evaluated', DateTime(timezone=False)),
    )

    try:
        watch_rule.create()
    except Exception:
        meta.drop_all(tables=tables)
        raise

    watch_data = Table(
        'watch_data', meta,
        Column('id', Integer, primary_key=True),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('data', Text()),
        Column('watch_rule_id', Integer, ForeignKey("watch_rule.id"),
               nullable=False),
    )

    try:
        watch_data.create()
    except Exception:
        meta.drop_all(tables=tables)
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    watch_rule = Table('watch_rule', meta, autoload=True)
    watch_rule.drop()
    watch_data = Table('watch_data', meta, autoload=True)
    watch_data.drop()
