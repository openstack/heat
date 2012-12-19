from sqlalchemy import *
from migrate import *
from heat.openstack.common import uuidutils


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    stack = Table('stack', meta, autoload=True)
    event = Table('event', meta, autoload=True)
    resource = Table('resource', meta, autoload=True)

    dialect = migrate_engine.url.get_dialect().name

    if not dialect.startswith('sqlite'):
        fkeys = list(event.c.stack_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[event.c.stack_id],
                refcolumns=[stack.c.id],
                name=fkey_name).drop()

        fkeys = list(resource.c.stack_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[resource.c.stack_id],
                refcolumns=[stack.c.id],
                name=fkey_name).drop()

    stack.c.id.alter(
        String(36), primary_key=True,
        default=uuidutils.generate_uuid)
    event.c.stack_id.alter(String(36), nullable=False)
    resource.c.stack_id.alter(String(36), nullable=False)

    fkeys = list(event.c.stack_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(
            columns=[event.c.stack_id],
            refcolumns=[stack.c.id],
            name=fkey_name).create()

    fkeys = list(resource.c.stack_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(
            columns=[resource.c.stack_id],
            refcolumns=[stack.c.id],
            name=fkey_name).create()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    dialect = migrate_engine.url.get_dialect().name

    if dialect.startswith('sqlite'):
        return

    stack = Table('stack', meta, autoload=True)
    event = Table('event', meta, autoload=True)
    resource = Table('resource', meta, autoload=True)

    fkeys = list(event.c.stack_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(
            columns=[event.c.stack_id],
            refcolumns=[stack.c.id],
            name=fkey_name).drop()

    fkeys = list(resource.c.stack_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(
            columns=[resource.c.stack_id],
            refcolumns=[stack.c.id],
            name=fkey_name).drop()

    stack.c.id.alter(
        Integer, primary_key=True,
        default=utils.generate_uuid)
    event.c.stack_id.alter(Integer, nullable=False)
    resource.c.stack_id.alter(Integer, nullable=False)

    fkeys = list(event.c.stack_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(
            columns=[event.c.stack_id],
            refcolumns=[stack.c.id],
            name=fkey_name).create()

    fkeys = list(resource.c.stack_id.foreign_keys)
    if fkeys:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(
            columns=[resource.c.stack_id],
            refcolumns=[stack.c.id],
            name=fkey_name).create()
