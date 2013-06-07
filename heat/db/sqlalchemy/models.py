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

from sqlalchemy import *
from sqlalchemy.orm import relationship, backref, object_mapper
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import types as types
from json import dumps
from json import loads
from heat.openstack.common import uuidutils
from heat.openstack.common import timeutils
from heat.db.sqlalchemy.session import get_session
from sqlalchemy.orm.session import Session

BASE = declarative_base()


class Json(types.TypeDecorator, types.MutableType):
    impl = types.Text

    def process_bind_param(self, value, dialect):
        return dumps(value)

    def process_result_value(self, value, dialect):
        return loads(value)


class HeatBase(object):
    """Base class for Heat Models."""
    __table_args__ = {'mysql_engine': 'InnoDB'}
    __table_initialized__ = False
    created_at = Column(DateTime, default=timeutils.utcnow)
    updated_at = Column(DateTime, onupdate=timeutils.utcnow)

    def save(self, session=None):
        """Save this object."""
        if not session:
            session = Session.object_session(self)
            if not session:
                session = get_session()
        session.add(self)
        try:
            session.flush()
        except IntegrityError as e:
            if str(e).endswith('is not unique'):
                raise exception.Duplicate(str(e))
            else:
                raise

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
        self.deleted = True
        self.deleted_at = timeutils.utcnow()
        if not session:
            session = Session.object_session(self)
            if not session:
                session = get_session()
        session.delete(self)
        session.flush()

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __iter__(self):
        self._i = iter(object_mapper(self).columns)
        return self

    def next(self):
        n = self._i.next().name
        return n, getattr(self, n)

    def update(self, values):
        """Make the model object behave like a dict."""
        for k, v in values.iteritems():
            setattr(self, k, v)

    def update_and_save(self, values, session=None):
        if not session:
            session = Session.object_session(self)
            if not session:
                session = get_session()
        session.begin()
        for k, v in values.iteritems():
            setattr(self, k, v)
        session.commit()

    def iteritems(self):
        """Make the model object behave like a dict.

        Includes attributes from joins.
        """
        local = dict(self)
        joined = dict([(k, v) for k, v in self.__dict__.iteritems()
                      if not k[0] == '_'])
        local.update(joined)
        return local.iteritems()


class RawTemplate(BASE, HeatBase):
    """Represents an unparsed template which should be in JSON format."""

    __tablename__ = 'raw_template'
    id = Column(Integer, primary_key=True)
    template = Column(Json)


class Stack(BASE, HeatBase):
    """Represents a stack created by the heat engine."""

    __tablename__ = 'stack'

    id = Column(String, primary_key=True, default=uuidutils.generate_uuid)
    name = Column(String)
    raw_template_id = Column(
        Integer,
        ForeignKey('raw_template.id'),
        nullable=False)
    raw_template = relationship(RawTemplate, backref=backref('stack'))
    username = Column(String)
    tenant = Column(String)
    status = Column('status', String)
    status_reason = Column('status_reason', String)
    parameters = Column('parameters', Json)
    user_creds_id = Column(
        Integer,
        ForeignKey('user_creds.id'),
        nullable=False)
    owner_id = Column(String, nullable=True)
    timeout = Column(Integer)
    disable_rollback = Column(Boolean)


class UserCreds(BASE, HeatBase):
    """
    Represents user credentials and mirrors the 'context'
    handed in by wsgi.
    """

    __tablename__ = 'user_creds'

    id = Column(Integer, primary_key=True)
    username = Column(String)
    password = Column(String)
    service_user = Column(String)
    service_password = Column(String)
    tenant = Column(String)
    auth_url = Column(String)
    aws_auth_url = Column(String)
    tenant_id = Column(String)
    aws_creds = Column(String)
    stack = relationship(Stack, backref=backref('user_creds'))


class Event(BASE, HeatBase):
    """Represents an event generated by the heat engine."""

    __tablename__ = 'event'

    id = Column(Integer, primary_key=True)
    stack_id = Column(String, ForeignKey('stack.id'), nullable=False)
    stack = relationship(Stack, backref=backref('events'))

    name = Column(String)
    logical_resource_id = Column(String)
    physical_resource_id = Column(String)
    resource_status_reason = Column(String)
    resource_type = Column(String)
    resource_properties = Column(PickleType)


class Resource(BASE, HeatBase):
    """Represents a resource created by the heat engine."""

    __tablename__ = 'resource'

    id = Column(Integer, primary_key=True)
    state = Column('state', String)
    name = Column('name', String, nullable=False)
    nova_instance = Column('nova_instance', String)
    state_description = Column('state_description', String)
    # odd name as "metadata" is reserved
    rsrc_metadata = Column('rsrc_metadata', Json)

    stack_id = Column(String, ForeignKey('stack.id'), nullable=False)
    stack = relationship(Stack, backref=backref('resources'))


class WatchRule(BASE, HeatBase):
    """Represents a watch_rule created by the heat engine."""

    __tablename__ = 'watch_rule'

    id = Column(Integer, primary_key=True)
    name = Column('name', String, nullable=False)
    rule = Column('rule', Json)
    state = Column('state', String)
    last_evaluated = Column(DateTime, default=timeutils.utcnow)

    stack_id = Column(String, ForeignKey('stack.id'), nullable=False)
    stack = relationship(Stack, backref=backref('watch_rule'))


class WatchData(BASE, HeatBase):
    """Represents a watch_data created by the heat engine."""

    __tablename__ = 'watch_data'

    id = Column(Integer, primary_key=True)
    data = Column('data', Json)

    watch_rule_id = Column(
        Integer,
        ForeignKey('watch_rule.id'),
        nullable=False)
    watch_rule = relationship(WatchRule, backref=backref('watch_data'))
