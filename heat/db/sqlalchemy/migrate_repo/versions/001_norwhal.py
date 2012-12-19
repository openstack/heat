from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    rawtemplate = Table(
        'raw_template', meta,
        Column('id', Integer, primary_key=True),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('template', Text()),
    )

    stack = Table(
        'stack', meta,
        Column('id', Integer, primary_key=True),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('name', String(
            length=255,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False)),
        Column('raw_template_id', Integer, ForeignKey("raw_template.id"),
               nullable=False),
    )

    event = Table(
        'event', meta,
        Column('id', Integer, primary_key=True),
        Column('stack_id', Integer, ForeignKey("stack.id"), nullable=False),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('name', String(
            length=255,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False)),
    )

    resource = Table(
        'resource', meta,
        Column('id', Integer, primary_key=True),
        Column('nova_instance', String(
            length=255,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False)),
        Column('name', String(
            length=255,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False)),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('state', String(
            length=255,
            convert_unicode=False,
            assert_unicode=None,
            unicode_error=None,
            _warn_on_bytestring=False)),
        Column('state_description', String(length=255, convert_unicode=False,
                                           assert_unicode=None,
                                           unicode_error=None,
                                           _warn_on_bytestring=False)),
        Column('parsed_template_id', Integer, ForeignKey("parsed_template.id"),
               nullable=True),
        Column('stack_id', Integer, ForeignKey("stack.id"), nullable=False),
        Column('depends_on', Integer),
    )

    parsedtemplate = Table(
        'parsed_template', meta,
        Column('id', Integer, primary_key=True),
        Column('raw_template_id', Integer, ForeignKey("raw_template.id"),
               nullable=False),
        Column('template', Text()),
    )

    tables = [rawtemplate, stack, event, parsedtemplate, resource]
    for table in tables:
        try:
            table.create()
        except Exception:
            meta.drop_all(tables=tables)
            raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    rawtemplate = Table('raw_template', meta, autoload=True)
    event = Table('event', meta, autoload=True)
    resource = Table('resource', meta, autoload=True)
    parsedtemplate = Table('parsed_template', meta, autoload=True)
    stack = Table('stack', meta, autoload=True)

    for table in (event, stack, resource, parsedtemplate, rawtemplate):
        table.drop()
