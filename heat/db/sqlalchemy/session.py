# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Session Handling for SQLAlchemy backend."""

import logging
import sqlalchemy.interfaces
import sqlalchemy.orm
from sqlalchemy.exc import DisconnectionError

from heat.db import api as db_api
from heat.openstack.common import cfg

logger = logging.getLogger('heat.db.sqlalchemy.session')
_ENGINE = None
_MAKER = None


class Error(Exception):
    pass


class DBError(Error):
    """Wraps an implementation specific exception."""
    def __init__(self, inner_exception=None):
        self.inner_exception = inner_exception
        super(DBError, self).__init__(str(inner_exception))


def _wrap_db_error(f):
    def _wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except UnicodeEncodeError:
            raise InvalidUnicodeParameter()
        except Exception, e:
            logger.exception(_('DB exception wrapped.'))
            raise DBError(e)
    _wrap.func_name = f.func_name
    return _wrap


def get_session(autocommit=True, expire_on_commit=False):
    """Return a SQLAlchemy session."""
    global _ENGINE, _MAKER

    if _MAKER is None or _ENGINE is None:
        _ENGINE = get_engine()
        _MAKER = get_maker(_ENGINE, autocommit, expire_on_commit)
    session = _MAKER()
    session.query = _wrap_db_error(session.query)
    session.flush = _wrap_db_error(session.flush)
    return session


class SynchronousSwitchListener(sqlalchemy.interfaces.PoolListener):

    """Switch sqlite connections to non-synchronous mode"""

    def connect(self, dbapi_con, con_record):
        dbapi_con.execute("PRAGMA synchronous = OFF")


class MySQLPingListener(object):

    """
    Ensures that MySQL connections checked out of the
    pool are alive.

    Borrowed from:
    http://groups.google.com/group/sqlalchemy/msg/a4ce563d802c929f
    """

    def checkout(self, dbapi_con, con_record, con_proxy):
        try:
            dbapi_con.cursor().execute('select 1')
        except dbapi_con.OperationalError, ex:
            if ex.args[0] in (2006, 2013, 2014, 2045, 2055):
                logger.warn('Got mysql server has gone away: %s', ex)
                raise DisconnectionError("Database server went away")
            else:
                raise


def get_engine():
    """Return a SQLAlchemy engine."""
    connection_dict = sqlalchemy.engine.url.make_url(_get_sql_connection())
    engine_args = {
        "pool_recycle": _get_sql_idle_timeout(),
        "echo": False,
        'convert_unicode': True,
    }

    if 'mysql' in connection_dict.drivername:
        engine_args['listeners'] = [MySQLPingListener()]

    return sqlalchemy.create_engine(_get_sql_connection(), **engine_args)


def get_maker(engine, autocommit=True, expire_on_commit=False):
    """Return a SQLAlchemy sessionmaker using the given engine."""
    ses = sqlalchemy.orm.sessionmaker(bind=engine,
                                       autocommit=autocommit,
                                       expire_on_commit=expire_on_commit)
    return sqlalchemy.orm.scoped_session(ses)


def _get_sql_connection():
    return db_api.SQL_CONNECTION


def _get_sql_idle_timeout():
    return db_api.SQL_IDLE_TIMEOUT
