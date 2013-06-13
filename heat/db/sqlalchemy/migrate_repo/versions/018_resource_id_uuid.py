import sqlalchemy
from heat.openstack.common import uuidutils


def upgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    resource = sqlalchemy.Table('resource', meta, autoload=True)

    resource.c.id.alter(sqlalchemy.String(36), primary_key=True,
                        default=uuidutils.generate_uuid)


def downgrade(migrate_engine):
    meta = sqlalchemy.MetaData(bind=migrate_engine)

    resource = sqlalchemy.Table('resource', meta, autoload=True)

    resource.c.id.alter(sqlalchemy.Integer, primary_key=True)
