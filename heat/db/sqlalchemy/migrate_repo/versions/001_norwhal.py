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

    event = Table(
        'event', meta,
        Column('id', Integer, primary_key=True),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('name', String(length=255, convert_unicode=False,
                      assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
    )

    resource = Table(
        'resource', meta,
        Column('id', Integer, primary_key=True),
        Column('instance_id', String(length=255, convert_unicode=False,
              assert_unicode=None,
              unicode_error=None, _warn_on_bytestring=False)),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('state', Integer()),
        Column('state_description', String(length=255, convert_unicode=False,
                                           assert_unicode=None,
                                           unicode_error=None, 
                                           _warn_on_bytestring=False)),
    )

    parsedtemplate = Table(
        'parsed_template', meta,
        Column('id', Integer, primary_key=True),
        Column('resource_id', Integer()),
        Column('template', Text()),
    )

    tables = [rawtemplate, event, resource, parsedtemplate]
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

    for table in (rawtemplate, event, resource, parsedtemplate):
        table.drop()
