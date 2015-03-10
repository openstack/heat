#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import itertools
import uuid

import migrate
import migrate.changeset.constraint as constraint
from oslo_utils import timeutils
import sqlalchemy
from sqlalchemy.schema import DropConstraint, ForeignKeyConstraint

# "the upgrade plan" (might be wrong)
# 1. resource_data:
# 2.  rename resource_id to tmp_res_uuid
# 3.  add resource_id as int
# 4. resource:
# 5.  full schema change
# 6. resource_data:
# 7.  populate the correct resource_id
# 8.  drop tmp_res_uuid and make resource_id a foreignkey


def upgrade_resource_data_pre(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    rd_table = sqlalchemy.Table('resource_data', meta, autoload=True)
    res_table = sqlalchemy.Table('resource', meta, autoload=True)

    # remove foreignkey on resource_id
    inspector = sqlalchemy.inspect(migrate_engine)
    fkc_name = inspector.get_foreign_keys('resource_data')[0]['name']
    fkc = ForeignKeyConstraint([rd_table.c.resource_id], [res_table.c.id],
                               fkc_name)
    migrate_engine.execute(DropConstraint(fkc))
    # migrate.ForeignKeyConstraint(columns=[rd_table.c.resource_id],
    #                              refcolumns=[res_table.c.id]).drop()
    # rename resource_id -> tmp_res_uuid
    rd_table.c.resource_id.alter('tmp_res_uuid', sqlalchemy.String(36))

    # create the new resource_id column (no foreignkey yet)
    res_id_column_kwargs = {}
    if migrate_engine.name == 'ibm_db_sa':
        # NOTE(mriedem): This is turned into a foreignkey key constraint
        # later so it must be non-nullable.
        res_id_column_kwargs['nullable'] = False
    res_id = sqlalchemy.Column('resource_id', sqlalchemy.Integer,
                               **res_id_column_kwargs)
    rd_table.create_column(res_id)


def upgrade_sqlite_resource_data_pre(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    sqlalchemy.Table('resource', meta, autoload=True)
    rd_table = sqlalchemy.Table(
        'new_resource_data', meta,
        sqlalchemy.Column('id',
                          sqlalchemy.Integer,
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('key', sqlalchemy.String(255)),
        sqlalchemy.Column('value', sqlalchemy.Text),
        sqlalchemy.Column('redact', sqlalchemy.Boolean),
        sqlalchemy.Column('decrypt_method', sqlalchemy.String(64)),
        sqlalchemy.Column('resource_id', sqlalchemy.Integer,
                          nullable=False),
        sqlalchemy.Column('tmp_res_uuid', sqlalchemy.String(36),
                          nullable=False))
    rd_table.create()

    prev_rd_table = sqlalchemy.Table('resource_data', meta, autoload=True)
    rd_list = list(prev_rd_table.select().order_by(
        sqlalchemy.sql.expression.asc(prev_rd_table.c.created_at))
        .execute())
    for rd in rd_list:
        values = {'key': rd.key,
                  'value': rd.value,
                  'redact': rd.redact,
                  'decrypt_method': rd.decrypt_method,
                  'resource_id': 0,
                  'tmp_res_uuid': rd.resource_id}
        migrate_engine.execute(rd_table.insert(values))

    prev_rd_table.drop()
    rd_table.rename('resource_data')


def upgrade_resource(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    res_table = sqlalchemy.Table('resource', meta, autoload=True)
    res_uuid_column_kwargs = {}
    if migrate_engine.name == 'ibm_db_sa':
        # NOTE(mriedem): DB2 10.5 doesn't support unique constraints over
        # nullable columns, it creates a unique index instead, so we have
        # to make the uuid column non-nullable in the DB2 case.
        res_uuid_column_kwargs['nullable'] = False
    res_uuid = sqlalchemy.Column('uuid', sqlalchemy.String(length=36),
                                 default=lambda: str(uuid.uuid4),
                                 **res_uuid_column_kwargs)
    res_table.create_column(res_uuid)
    if migrate_engine.name == 'postgresql':
        sequence = sqlalchemy.Sequence('res')
        sqlalchemy.schema.CreateSequence(sequence,
                                         bind=migrate_engine).execute()
        res_id = sqlalchemy.Column('tmp_id', sqlalchemy.Integer,
                                   server_default=sqlalchemy.text(
                                       "nextval('res')"))
    else:
        res_id_column_kwargs = {}
        if migrate_engine.name == 'ibm_db_sa':
            # NOTE(mriedem): This is turned into a primary key constraint
            # later so it must be non-nullable.
            res_id_column_kwargs['nullable'] = False
        res_id = sqlalchemy.Column('tmp_id', sqlalchemy.Integer,
                                   **res_id_column_kwargs)
    res_table.create_column(res_id)

    fake_autoincrement = itertools.count(1)

    res_list = res_table.select().order_by(
        sqlalchemy.sql.expression.asc(
            res_table.c.created_at)).execute().fetchall()
    for res in res_list:
        values = {'tmp_id': fake_autoincrement.next(), 'uuid': res.id}
        update = res_table.update().where(
            res_table.c.id == res.id).values(values)
        migrate_engine.execute(update)
    constraint_kwargs = {'table': res_table}
    if migrate_engine.name == 'ibm_db_sa':
        # NOTE(mriedem): DB2 gives a random name to the unique constraint
        # if one is not provided so let's set the standard name ourselves.
        constraint_kwargs['name'] = 'uniq_resource0uuid0'
    cons = constraint.UniqueConstraint('uuid', **constraint_kwargs)
    cons.create()
    if migrate_engine.name == 'postgresql':
        # resource_id_seq will be dropped in the case of removing `id` column
        # set owner to none for saving this sequence (it is needed in the
        # earlier migration)
        migrate_engine.execute('alter sequence resource_id_seq owned by none')

    res_table.c.id.drop()

    alter_kwargs = {}
    if migrate_engine.name == 'ibm_db_sa':
        alter_kwargs['nullable'] = False
    res_table.c.tmp_id.alter('id', sqlalchemy.Integer, **alter_kwargs)

    cons = constraint.PrimaryKeyConstraint('tmp_id', table=res_table)
    cons.create()

    if migrate_engine.name == 'ibm_db_sa':
        # NOTE(chenxiao): For DB2, setting "ID" column "autoincrement=True"
        # can't make sense after above "tmp_id=>id" transformation,
        # so should work around it.
        sql = ("ALTER TABLE RESOURCE ALTER COLUMN ID SET GENERATED BY "
               "DEFAULT AS IDENTITY (START WITH 1, INCREMENT BY 1)")
        migrate_engine.execute(sql)
    else:
        res_table.c.tmp_id.alter(sqlalchemy.Integer, autoincrement=True)


def upgrade_resource_data_post(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    res_table = sqlalchemy.Table('resource', meta, autoload=True)
    rd_table = sqlalchemy.Table('resource_data', meta, autoload=True)

    # set: resource_data.resource_id = resource.id
    res_list = res_table.select().order_by(
        sqlalchemy.sql.expression.asc(
            res_table.c.created_at)).execute().fetchall()
    for res in res_list:
        values = {'resource_id': res.id}
        update = rd_table.update().where(
            rd_table.c.tmp_res_uuid == res.uuid).values(values)
        migrate_engine.execute(update)

    # set foreignkey on resource_id
    if migrate_engine.name == 'mysql':
        inspector = sqlalchemy.inspect(migrate_engine)
        name = inspector.get_indexes('resource_data')[0]['name']
        sqlalchemy.Index(name, rd_table.c.resource_id).drop()

    cons = migrate.ForeignKeyConstraint(columns=[rd_table.c.resource_id],
                                        refcolumns=[res_table.c.id])
    cons.create()
    rd_table.c.resource_id.alter(nullable=False)

    rd_table.c.tmp_res_uuid.drop()


def upgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        upgrade_sqlite_resource_data_pre(migrate_engine)
        upgrade_sqlite_resource(migrate_engine)
    else:
        upgrade_resource_data_pre(migrate_engine)
        upgrade_resource(migrate_engine)

    upgrade_resource_data_post(migrate_engine)


def upgrade_sqlite_resource(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    # (pafuent) Here it isn't recommended to import the table from the models,
    # because in future migrations the model could change and this migration
    # could fail.
    # I know it is ugly but it's the only way that I found to 'freeze'
    # the model state for this migration.
    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    res_table = sqlalchemy.Table(
        'new_resource', meta,
        sqlalchemy.Column('id', sqlalchemy.Integer, primary_key=True),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey(stack_table.c.id),
                          nullable=False),
        sqlalchemy.Column('uuid', sqlalchemy.String(36),
                          default=lambda: str(uuid.uuid4()),
                          unique=True),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('nova_instance', sqlalchemy.String(255)),
        sqlalchemy.Column('action', sqlalchemy.String(255)),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('rsrc_metadata', sqlalchemy.Text),
        sqlalchemy.Column('properties_data', sqlalchemy.Text),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                          default=timeutils.utcnow),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime,
                          onupdate=timeutils.utcnow))
    res_table.create()

    prev_res_table = sqlalchemy.Table('resource', meta, autoload=True)
    res_list = list(prev_res_table.select().order_by(
        sqlalchemy.sql.expression.asc(prev_res_table.c.created_at))
        .execute())
    for res in res_list:
        values = {
            'stack_id': res.stack_id,
            'uuid': res.id,
            'name': res.name,
            'nova_instance': res.nova_instance,
            'action': res.action,
            'status': res.status,
            'status_reason': res.status_reason,
            'rsrc_metadata': res.rsrc_metadata,
            'properties_data': res.properties_data,
            'created_at': res.created_at,
            'updated_at': res.updated_at}
        migrate_engine.execute(res_table.insert(values))

    prev_res_table.drop()
    res_table.rename('resource')


def downgrade(migrate_engine):
    if migrate_engine.name == 'sqlite':
        downgrade_sqlite_resource_data_pre(migrate_engine)
        downgrade_sqlite_resource(migrate_engine)
    else:
        downgrade_resource_data_pre(migrate_engine)
        downgrade_resource(migrate_engine)

    downgrade_resource_data_post(migrate_engine)


def downgrade_resource_data_pre(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    rd_table = sqlalchemy.Table('resource_data', meta, autoload=True)
    res_table = sqlalchemy.Table('resource', meta, autoload=True)

    # remove foreignkey on resource_id
    inspector = sqlalchemy.inspect(migrate_engine)
    fkc_name = inspector.get_foreign_keys('resource_data')[0]['name']
    fkc = ForeignKeyConstraint([rd_table.c.resource_id], [res_table.c.id],
                               fkc_name)
    migrate_engine.execute(DropConstraint(fkc))

    # rename resource_id -> tmp_res_id
    rd_table.c.resource_id.alter(name='tmp_res_id')

    # create the new resource_id column (no foreignkey yet)
    res_id_column_kwargs = {}
    if migrate_engine.name == 'ibm_db_sa':
        # NOTE(mriedem): This is turned into a foreignkey key constraint
        # later so it must be non-nullable.
        res_id_column_kwargs['nullable'] = False
    res_id = sqlalchemy.Column('resource_id', sqlalchemy.String(36),
                               **res_id_column_kwargs)
    rd_table.create_column(res_id)

    # reload metadata due to some strange behaviour of sqlalchemy
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    rd_table = sqlalchemy.Table('resource_data', meta, autoload=True)

    res_list = res_table.select().order_by(
        sqlalchemy.sql.expression.asc(
            res_table.c.created_at)).execute().fetchall()
    for res in res_list:
        values = {'resource_id': res.uuid}
        update = rd_table.update().where(
            rd_table.c.tmp_res_id == res.id).values(values)
        migrate_engine.execute(update)


def downgrade_sqlite_resource_data_pre(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)
    sqlalchemy.Table('resource', meta, autoload=True)
    rd_table = sqlalchemy.Table(
        'new_resource_data', meta,
        sqlalchemy.Column('id',
                          sqlalchemy.Integer,
                          primary_key=True,
                          nullable=False),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime),
        sqlalchemy.Column('key', sqlalchemy.String(255)),
        sqlalchemy.Column('value', sqlalchemy.Text),
        sqlalchemy.Column('redact', sqlalchemy.Boolean),
        sqlalchemy.Column('decrypt_method', sqlalchemy.String(64)),
        sqlalchemy.Column('resource_id', sqlalchemy.Integer,
                          nullable=False),
        sqlalchemy.Column('tmp_res_id', sqlalchemy.Integer,
                          nullable=False))
    rd_table.create()

    prev_rd_table = sqlalchemy.Table('resource_data', meta, autoload=True)
    rd_list = list(prev_rd_table.select().order_by(
        sqlalchemy.sql.expression.asc(prev_rd_table.c.created_at))
        .execute())
    for rd in rd_list:
        values = {'key': rd.key,
                  'value': rd.value,
                  'redact': rd.redact,
                  'decrypt_method': rd.decrypt_method,
                  'resource_id': "foo",
                  'tmp_res_id': rd.resource_id}
        migrate_engine.execute(rd_table.insert(values))

    prev_rd_table.drop()
    rd_table.rename('resource_data')


def downgrade_resource(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    res_table = sqlalchemy.Table('resource', meta, autoload=True)

    res_id_column_kwargs = {}
    if migrate_engine.name == 'ibm_db_sa':
        res_id_column_kwargs['nullable'] = False

    res_id = sqlalchemy.Column('tmp_id', sqlalchemy.String(length=36),
                               default=lambda: str(uuid.uuid4),
                               **res_id_column_kwargs)
    res_id.create(res_table)

    res_list = res_table.select().execute()
    for res in res_list:
        values1 = {'tmp_id': res.uuid}
        update = res_table.update().where(
            res_table.c.uuid == res.uuid).values(values1)
        migrate_engine.execute(update)

    res_table.c.id.drop()
    res_table.c.uuid.drop()

    cons = constraint.PrimaryKeyConstraint('tmp_id', table=res_table)
    cons.create()

    alter_kwargs = {}
    # NOTE(mriedem): DB2 won't allow a primary key on a nullable column so
    # we have to make it non-nullable.
    if migrate_engine.name == 'ibm_db_sa':
        alter_kwargs['nullable'] = False
    res_table.c.tmp_id.alter('id', default=lambda: str(uuid.uuid4),
                             **alter_kwargs)
    if migrate_engine.name == 'postgresql':
        sequence = sqlalchemy.Sequence('res')
        sqlalchemy.schema.DropSequence(sequence, bind=migrate_engine).execute()


def downgrade_sqlite_resource(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    # (pafuent) Here it isn't recommended to import the table from the models,
    # because in future migrations the model could change and this migration
    # could fail.
    # I know it is ugly but it's the only way that I found to 'freeze'
    # the model state for this migration.
    stack_table = sqlalchemy.Table('stack', meta, autoload=True)
    res_table = sqlalchemy.Table(
        'new_resource', meta,
        sqlalchemy.Column('id', sqlalchemy.String(36),
                          default=lambda: str(uuid.uuid4())),
        sqlalchemy.Column('stack_id', sqlalchemy.String(36),
                          sqlalchemy.ForeignKey(stack_table.c.id),
                          nullable=False),
        sqlalchemy.Column('name', sqlalchemy.String(255)),
        sqlalchemy.Column('nova_instance', sqlalchemy.String(255)),
        sqlalchemy.Column('action', sqlalchemy.String(255)),
        sqlalchemy.Column('status', sqlalchemy.String(255)),
        sqlalchemy.Column('status_reason', sqlalchemy.String(255)),
        sqlalchemy.Column('rsrc_metadata', sqlalchemy.Text),
        sqlalchemy.Column('properties_data', sqlalchemy.Text),
        sqlalchemy.Column('created_at', sqlalchemy.DateTime,
                          default=timeutils.utcnow),
        sqlalchemy.Column('updated_at', sqlalchemy.DateTime,
                          onupdate=timeutils.utcnow))
    res_table.create()

    prev_res_table = sqlalchemy.Table('resource', meta, autoload=True)
    res_list = prev_res_table.select().execute().fetchall()
    for res in res_list:
        values = {
            'id': res.uuid,
            'stack_id': res.stack_id,
            'name': res.name,
            'nova_instance': res.nova_instance,
            'status': res.status,
            'status_reason': res.status_reason,
            'rsrc_metadata': res.rsrc_metadata,
            'properties_data': res.properties_data,
            'created_at': res.created_at,
            'updated_at': res.updated_at}
        migrate_engine.execute(res_table.insert(values))

    prev_res_table.drop()
    res_table.rename('resource')


def downgrade_resource_data_post(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    res_table = sqlalchemy.Table('resource', meta, autoload=True)
    rd_table = sqlalchemy.Table('resource_data', meta, autoload=True)

    # set: resource_data.resource_id = resource.id
    if migrate_engine.name == 'sqlite':
        res_list = res_table.select().order_by(
            sqlalchemy.sql.expression.asc(
                res_table.c.created_at)).execute().fetchall()
        for res in res_list:
            values = {'resource_id': res.id}
            update = rd_table.update().where(
                rd_table.c.tmp_res_id == res.id).values(values)
            migrate_engine.execute(update)

    # set foreignkey on resource_id
    if migrate_engine.name == 'mysql':
        sqlalchemy.Index('resource_data_resource_id_fkey',
                         rd_table.c.resource_id).drop()
    cons = migrate.ForeignKeyConstraint(columns=[rd_table.c.resource_id],
                                        refcolumns=[res_table.c.id])
    cons.create()

    rd_table.c.resource_id.alter(nullable=False)

    rd_table.c.tmp_res_id.drop()
