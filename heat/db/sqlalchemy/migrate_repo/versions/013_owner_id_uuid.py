from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    stack = Table('stack', meta, autoload=True)

    dialect = migrate_engine.url.get_dialect().name

    if not dialect.startswith('sqlite'):
        fkeys = list(stack.c.owner_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[stack.c.owner_id],
                    refcolumns=[stack.c.id],
                    name=fkey_name).drop()

    stack.c.owner_id.alter(String(36), nullable=True)

    fkeys = list(stack.c.owner_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(columns=[stack.c.owner_id],
                refcolumns=[stack.c.id],
                name=fkey_name).create()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    dialect = migrate_engine.url.get_dialect().name

    if dialect.startswith('sqlite'):
        return

    stack = Table('stack', meta, autoload=True)

    fkeys = list(stack.c.owner_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(columns=[stack.c.owner_id],
                refcolumns=[stack.c.id],
                name=fkey_name).drop()

    stack.c.owner_id.alter(Integer, nullable=True)

    fkeys = list(event.c.stack_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(columns=[event.c.stack_id],
                refcolumns=[stack.c.id],
                name=fkey_name).create()

    fkeys = list(stack.c.owner_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(columns=[stack.c.owner_id],
                refcolumns=[stack.c.id],
                name=fkey_name).create()
