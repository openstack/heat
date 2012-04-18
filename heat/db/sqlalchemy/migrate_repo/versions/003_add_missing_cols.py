from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    parsed_template = Table('parsed_template', meta, autoload=True)

    Column('created_at', DateTime(timezone=False)).create(parsed_template)
    Column('updated_at', DateTime(timezone=False)).create(parsed_template)


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    parsed_template = Table('parsed_template', meta, autoload=True)

    parsed_template.c.created_at.drop()
    parsed_template.c.updated_at.drop()
