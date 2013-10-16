# vim: tabstop=4 shiftwidth=4 softtabstop=4
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
"""
SQLAlchemy models for heat data.
"""

import sqlalchemy

from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import types
from json import dumps
from json import loads
from heat.openstack.common import uuidutils
from heat.openstack.common import timeutils
from heat.openstack.common.db.sqlalchemy import models
from heat.openstack.common.db.sqlalchemy import session
from sqlalchemy.orm.session import Session

BASE = declarative_base()
get_session = session.get_session


class Json(types.TypeDecorator):
    impl = types.Text

    def load_dialect_impl(self, dialect):
        if dialect.name == 'mysql':
            return dialect.type_descriptor(mysql.LONGTEXT())
        else:
            return self.impl

    def process_bind_param(self, value, dialect):
        return dumps(value)

    def process_result_value(self, value, dialect):
        return loads(value)

# TODO(leizhang) When we removed sqlalchemy 0.7 dependence
# we can import MutableDict directly and remove ./mutable.py
try:
    from sqlalchemy.ext.mutable import MutableDict as sa_MutableDict
    sa_MutableDict.associate_with(Json)
except ImportError:
    from heat.db.sqlalchemy.mutable import MutableDict
    MutableDict.associate_with(Json)


class HeatBase(models.ModelBase, models.TimestampMixin):
    """Base class for Heat Models."""
    __table_args__ = {'mysql_engine': 'InnoDB'}

    def expire(self, session=None, attrs=None):
        """Expire this object ()."""
        if not session:
            session = Session.object_session(self)
            if not session:
                session = get_session()
        session.expire(self, attrs)

    def refresh(self, session=None, attrs=None):
        """Refresh this object."""
        if not session:
            session = Session.object_session(self)
            if not session:
                session = get_session()
        session.refresh(self, attrs)

    def delete(self, session=None):
        """Delete this object."""
        if not session:
            session = Session.object_session(self)
            if not session:
                session = get_session()
        session.delete(self)
        session.flush()

    def update_and_save(self, values, session=None):
        if not session:
            session = Session.object_session(self)
            if not session:
                session = get_session()
        session.begin()
        for k, v in values.iteritems():
            setattr(self, k, v)
        session.commit()


class SoftDelete(object):
    deleted_at = sqlalchemy.Column(sqlalchemy.DateTime)

    def soft_delete(self, session=None):
        """Mark this object as deleted."""
        self.update_and_save({'deleted_at': timeutils.utcnow()},
                             session=session)


class RawTemplate(BASE, HeatBase):
    """Represents an unparsed template which should be in JSON format."""

    __tablename__ = 'raw_template'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    template = sqlalchemy.Column(Json)


class Stack(BASE, HeatBase, SoftDelete):
    """Represents a stack created by the heat engine."""

    __tablename__ = 'stack'

    id = sqlalchemy.Column(sqlalchemy.String, primary_key=True,
                           default=uuidutils.generate_uuid)
    name = sqlalchemy.Column(sqlalchemy.String)
    raw_template_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('raw_template.id'),
        nullable=False)
    raw_template = relationship(RawTemplate, backref=backref('stack'))
    username = sqlalchemy.Column(sqlalchemy.String)
    tenant = sqlalchemy.Column(sqlalchemy.String)
    action = sqlalchemy.Column('action', sqlalchemy.String)
    status = sqlalchemy.Column('status', sqlalchemy.String)
    status_reason = sqlalchemy.Column('status_reason', sqlalchemy.String)
    parameters = sqlalchemy.Column('parameters', Json)
    user_creds_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('user_creds.id'),
        nullable=False)
    owner_id = sqlalchemy.Column(sqlalchemy.String, nullable=True)
    timeout = sqlalchemy.Column(sqlalchemy.Integer)
    disable_rollback = sqlalchemy.Column(sqlalchemy.Boolean)


class UserCreds(BASE, HeatBase):
    """
    Represents user credentials and mirrors the 'context'
    handed in by wsgi.
    """

    __tablename__ = 'user_creds'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    username = sqlalchemy.Column(sqlalchemy.String)
    password = sqlalchemy.Column(sqlalchemy.String)
    tenant = sqlalchemy.Column(sqlalchemy.String)
    auth_url = sqlalchemy.Column(sqlalchemy.String)
    tenant_id = sqlalchemy.Column(sqlalchemy.String)
    trust_id = sqlalchemy.Column(sqlalchemy.String)
    trustor_user_id = sqlalchemy.Column(sqlalchemy.String)
    stack = relationship(Stack, backref=backref('user_creds'))


class Event(BASE, HeatBase):
    """Represents an event generated by the heat engine."""

    __tablename__ = 'event'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    stack_id = sqlalchemy.Column(sqlalchemy.String,
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    stack = relationship(Stack, backref=backref('events'))

    resource_action = sqlalchemy.Column(sqlalchemy.String)
    resource_status = sqlalchemy.Column(sqlalchemy.String)
    resource_name = sqlalchemy.Column(sqlalchemy.String)
    physical_resource_id = sqlalchemy.Column(sqlalchemy.String)
    resource_status_reason = sqlalchemy.Column(sqlalchemy.String)
    resource_type = sqlalchemy.Column(sqlalchemy.String)
    resource_properties = sqlalchemy.Column(sqlalchemy.PickleType)


class ResourceData(BASE, HeatBase):
    """Key/value store of arbitrary, resource-specific data."""

    __tablename__ = 'resource_data'

    id = sqlalchemy.Column('id',
                           sqlalchemy.Integer,
                           primary_key=True,
                           nullable=False)
    key = sqlalchemy.Column('key', sqlalchemy.String)
    value = sqlalchemy.Column('value', sqlalchemy.String)
    redact = sqlalchemy.Column('redact', sqlalchemy.Boolean)
    resource_id = sqlalchemy.Column('resource_id',
                                    sqlalchemy.String,
                                    sqlalchemy.ForeignKey('resource.id'),
                                    nullable=False)


class Resource(BASE, HeatBase):
    """Represents a resource created by the heat engine."""

    __tablename__ = 'resource'

    id = sqlalchemy.Column(sqlalchemy.String,
                           primary_key=True,
                           default=uuidutils.generate_uuid)
    action = sqlalchemy.Column('action', sqlalchemy.String)
    status = sqlalchemy.Column('status', sqlalchemy.String)
    name = sqlalchemy.Column('name', sqlalchemy.String, nullable=False)
    nova_instance = sqlalchemy.Column('nova_instance', sqlalchemy.String)
    status_reason = sqlalchemy.Column('status_reason', sqlalchemy.String)
    # odd name as "metadata" is reserved
    rsrc_metadata = sqlalchemy.Column('rsrc_metadata', Json)

    stack_id = sqlalchemy.Column(sqlalchemy.String,
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    stack = relationship(Stack, backref=backref('resources'))
    data = relationship(ResourceData,
                        cascade="all,delete",
                        backref=backref('resource'))


class WatchRule(BASE, HeatBase):
    """Represents a watch_rule created by the heat engine."""

    __tablename__ = 'watch_rule'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    name = sqlalchemy.Column('name', sqlalchemy.String, nullable=False)
    rule = sqlalchemy.Column('rule', Json)
    state = sqlalchemy.Column('state', sqlalchemy.String)
    last_evaluated = sqlalchemy.Column(sqlalchemy.DateTime,
                                       default=timeutils.utcnow)

    stack_id = sqlalchemy.Column(sqlalchemy.String,
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    stack = relationship(Stack, backref=backref('watch_rule'))


class WatchData(BASE, HeatBase):
    """Represents a watch_data created by the heat engine."""

    __tablename__ = 'watch_data'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    data = sqlalchemy.Column('data', Json)

    watch_rule_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('watch_rule.id'),
        nullable=False)
    watch_rule = relationship(WatchRule, backref=backref('watch_data'))
