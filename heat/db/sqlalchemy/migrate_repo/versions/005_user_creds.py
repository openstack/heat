from sqlalchemy import *
from migrate import *


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    user_creds = Table(
        'user_creds', meta,
        Column('id', Integer, primary_key=True),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('username', String(length=255, convert_unicode=False,
                                  assert_unicode=None,
                                  unicode_error=None,
                                  _warn_on_bytestring=False)),
        Column('password', String(length=255, convert_unicode=False,
                                  assert_unicode=None,
                                  unicode_error=None,
                                  _warn_on_bytestring=False)),
        Column('service_user', String(length=255, convert_unicode=False,
                                      assert_unicode=None,
                                      unicode_error=None,
                                      _warn_on_bytestring=False)),
        Column('service_password', String(length=255, convert_unicode=False,
                                          assert_unicode=None,
                                          unicode_error=None,
                                          _warn_on_bytestring=False)),
        Column('tenant', String(length=1024, convert_unicode=False,
                                assert_unicode=None,
                                unicode_error=None,
                                _warn_on_bytestring=False)),
        Column('auth_url', Text()),
        Column('aws_auth_url', Text()),
        Column('tenant_id', String(length=256, convert_unicode=False,
                                assert_unicode=None,
                                unicode_error=None,
                                _warn_on_bytestring=False)),
        Column('aws_creds', Text())
    )

    user_creds.create()

    stack = Table('stack', meta, autoload=True)

    try:
        Column('user_creds_id', Integer, ForeignKey("user_creds.id"),
               nullable=False).create(stack)
    except sqlalchemy.exc.IntegrityError:
        stack.c.user_creds_id.drop()
        user_creds.drop()
        raise

    Column('username', String(length=256, convert_unicode=False,
                              assert_unicode=None,
                              unicode_error=None,
                              _warn_on_bytestring=False)).create(stack)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    stack = Table('stack', meta, autoload=True)
    user_creds = Table('user_creds', meta, autoload=True)

    stack.c.username.drop()

    def fk_name(table, ref_column):
        for fk in table.foreign_keys:
            if fk.column == ref_column:
                return fk.name

    fkc = ForeignKeyConstraint([stack.c.user_creds_id], [user_creds.c.id],
                               name=fk_name(stack, user_creds.c.id))
    fkc.drop()

    stack.c.user_creds_id.drop()
    user_creds.drop()
