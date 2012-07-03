from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    def fk_name(table, ref_column):
        for fk in table.foreign_keys:
            if fk.column == ref_column:
                return fk.name

    resource = Table('resource', meta, autoload=True)
    parsed_template = Table('parsed_template', meta, autoload=True)

    res_kc = ForeignKeyConstraint([resource.c.parsed_template_id],
                                  [parsed_template.c.id],
                                  name=fk_name(resource,
                                               parsed_template.c.id))
    try:
        res_kc.drop()
    except NotSupportedError:
        # SQLite (used in unit tests) cannot drop a Foreign Key constraint
        pass

    resource.c.parsed_template_id.drop()

    parsed_template.drop()


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    raw_template = Table('raw_template', meta, autoload=True)

    parsed_template = Table(
        'parsed_template', meta,
        Column('id', Integer, primary_key=True),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('raw_template_id', Integer, ForeignKey("raw_template.id"),
               nullable=False),
        Column('template', Text())
    )
    parsed_template.create()

    resource = Table('resource', meta, autoload=True)
    Column('parsed_template_id', Integer, ForeignKey('parsed_template.id'),
           nullable=True).create(resource)
