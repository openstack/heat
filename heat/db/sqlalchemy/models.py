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

import uuid

from oslo.db.sqlalchemy import models
import six
import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import backref
from sqlalchemy.orm import relationship
from sqlalchemy.orm.session import Session

from heat.db.sqlalchemy.types import Json
from heat.openstack.common import timeutils

BASE = declarative_base()


def get_session():
    from heat.db.sqlalchemy import api as db_api
    return db_api.get_session()


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
        for k, v in six.iteritems(values):
            setattr(self, k, v)
        session.commit()


class SoftDelete(object):
    deleted_at = sqlalchemy.Column(sqlalchemy.DateTime)

    def soft_delete(self, session=None):
        """Mark this object as deleted."""
        self.update_and_save({'deleted_at': timeutils.utcnow()},
                             session=session)


class StateAware(object):

    action = sqlalchemy.Column('action', sqlalchemy.String(255))
    status = sqlalchemy.Column('status', sqlalchemy.String(255))
    _status_reason = sqlalchemy.Column('status_reason', sqlalchemy.String(255))

    @property
    def status_reason(self):
        return self._status_reason

    @status_reason.setter
    def status_reason(self, reason):
        self._status_reason = reason and reason[:255] or ''


class RawTemplate(BASE, HeatBase):
    """Represents an unparsed template which should be in JSON format."""

    __tablename__ = 'raw_template'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    template = sqlalchemy.Column(Json)
    files = sqlalchemy.Column(Json)


class Stack(BASE, HeatBase, SoftDelete, StateAware):
    """Represents a stack created by the heat engine."""

    __tablename__ = 'stack'

    id = sqlalchemy.Column(sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    name = sqlalchemy.Column(sqlalchemy.String(255))
    raw_template_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('raw_template.id'),
        nullable=False)
    raw_template = relationship(RawTemplate, backref=backref('stack'))
    username = sqlalchemy.Column(sqlalchemy.String(256))
    tenant = sqlalchemy.Column(sqlalchemy.String(256))
    parameters = sqlalchemy.Column('parameters', Json)
    user_creds_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('user_creds.id'),
        nullable=False)
    owner_id = sqlalchemy.Column(sqlalchemy.String(36), nullable=True)
    timeout = sqlalchemy.Column(sqlalchemy.Integer)
    disable_rollback = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False)
    stack_user_project_id = sqlalchemy.Column(sqlalchemy.String(64),
                                              nullable=True)
    backup = sqlalchemy.Column('backup', sqlalchemy.Boolean)

    # Override timestamp column to store the correct value: it should be the
    # time the create/update call was issued, not the time the DB entry is
    # created/modified. (bug #1193269)
    updated_at = sqlalchemy.Column(sqlalchemy.DateTime)


class StackLock(BASE, HeatBase):
    """Store stack locks for deployments with multiple-engines."""

    __tablename__ = 'stack_lock'

    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
                                 sqlalchemy.ForeignKey('stack.id'),
                                 primary_key=True)
    engine_id = sqlalchemy.Column(sqlalchemy.String(36))


class UserCreds(BASE, HeatBase):
    """
    Represents user credentials and mirrors the 'context'
    handed in by wsgi.
    """

    __tablename__ = 'user_creds'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    username = sqlalchemy.Column(sqlalchemy.String(255))
    password = sqlalchemy.Column(sqlalchemy.String(255))
    decrypt_method = sqlalchemy.Column(sqlalchemy.String(64))
    tenant = sqlalchemy.Column(sqlalchemy.String(1024))
    auth_url = sqlalchemy.Column(sqlalchemy.String)
    tenant_id = sqlalchemy.Column(sqlalchemy.String(256))
    trust_id = sqlalchemy.Column(sqlalchemy.String(255))
    trustor_user_id = sqlalchemy.Column(sqlalchemy.String(64))
    stack = relationship(Stack, backref=backref('user_creds'))


class Event(BASE, HeatBase):
    """Represents an event generated by the heat engine."""

    __tablename__ = 'event'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    stack = relationship(Stack, backref=backref('events'))

    uuid = sqlalchemy.Column(sqlalchemy.String(36),
                             default=lambda: str(uuid.uuid4()),
                             unique=True)
    resource_action = sqlalchemy.Column(sqlalchemy.String(255))
    resource_status = sqlalchemy.Column(sqlalchemy.String(255))
    resource_name = sqlalchemy.Column(sqlalchemy.String(255))
    physical_resource_id = sqlalchemy.Column(sqlalchemy.String(255))
    _resource_status_reason = sqlalchemy.Column(
        'resource_status_reason', sqlalchemy.String(255))
    resource_type = sqlalchemy.Column(sqlalchemy.String(255))
    resource_properties = sqlalchemy.Column(sqlalchemy.PickleType)

    @property
    def resource_status_reason(self):
        return self._resource_status_reason

    @resource_status_reason.setter
    def resource_status_reason(self, reason):
        self._resource_status_reason = reason and reason[:255] or ''


class ResourceData(BASE, HeatBase):
    """Key/value store of arbitrary, resource-specific data."""

    __tablename__ = 'resource_data'

    id = sqlalchemy.Column('id',
                           sqlalchemy.Integer,
                           primary_key=True,
                           nullable=False)
    key = sqlalchemy.Column('key', sqlalchemy.String(255))
    value = sqlalchemy.Column('value', sqlalchemy.String)
    redact = sqlalchemy.Column('redact', sqlalchemy.Boolean)
    decrypt_method = sqlalchemy.Column(sqlalchemy.String(64))
    resource_id = sqlalchemy.Column('resource_id',
                                    sqlalchemy.String(36),
                                    sqlalchemy.ForeignKey('resource.id'),
                                    nullable=False)


class Resource(BASE, HeatBase, StateAware):
    """Represents a resource created by the heat engine."""

    __tablename__ = 'resource'

    id = sqlalchemy.Column(sqlalchemy.String(36),
                           primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    name = sqlalchemy.Column('name', sqlalchemy.String(255), nullable=True)
    nova_instance = sqlalchemy.Column('nova_instance', sqlalchemy.String(255))
    # odd name as "metadata" is reserved
    rsrc_metadata = sqlalchemy.Column('rsrc_metadata', Json)

    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    stack = relationship(Stack, backref=backref('resources'))
    data = relationship(ResourceData,
                        cascade="all,delete",
                        backref=backref('resource'))

    # Override timestamp column to store the correct value: it should be the
    # time the create/update call was issued, not the time the DB entry is
    # created/modified. (bug #1193269)
    updated_at = sqlalchemy.Column(sqlalchemy.DateTime)
    properties_data = sqlalchemy.Column('properties_data', Json)


class WatchRule(BASE, HeatBase):
    """Represents a watch_rule created by the heat engine."""

    __tablename__ = 'watch_rule'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    name = sqlalchemy.Column('name', sqlalchemy.String(255), nullable=True)
    rule = sqlalchemy.Column('rule', Json)
    state = sqlalchemy.Column('state', sqlalchemy.String(255))
    last_evaluated = sqlalchemy.Column(sqlalchemy.DateTime,
                                       default=timeutils.utcnow)

    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
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


class SoftwareConfig(BASE, HeatBase):
    """
    Represents a software configuration resource to be applied to
    one or more servers.
    """

    __tablename__ = 'software_config'

    id = sqlalchemy.Column('id', sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    name = sqlalchemy.Column('name', sqlalchemy.String(255),
                             nullable=True)
    group = sqlalchemy.Column('group', sqlalchemy.String(255))
    config = sqlalchemy.Column('config', Json)
    tenant = sqlalchemy.Column(
        'tenant', sqlalchemy.String(64), nullable=False)


class SoftwareDeployment(BASE, HeatBase, StateAware):
    """
    Represents applying a software configuration resource to a
    single server resource.
    """

    __tablename__ = 'software_deployment'

    id = sqlalchemy.Column('id', sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    config_id = sqlalchemy.Column(
        'config_id',
        sqlalchemy.String(36),
        sqlalchemy.ForeignKey('software_config.id'),
        nullable=False)
    config = relationship(SoftwareConfig, backref=backref('deployments'))
    server_id = sqlalchemy.Column('server_id', sqlalchemy.String(36),
                                  nullable=False)
    input_values = sqlalchemy.Column('input_values', Json)
    output_values = sqlalchemy.Column('output_values', Json)
    tenant = sqlalchemy.Column(
        'tenant', sqlalchemy.String(64), nullable=False)
    stack_user_project_id = sqlalchemy.Column(sqlalchemy.String(64),
                                              nullable=True)


class Snapshot(BASE, HeatBase):

    __tablename__ = 'snapshot'

    id = sqlalchemy.Column('id', sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    name = sqlalchemy.Column('name', sqlalchemy.String(255), nullable=True)
    data = sqlalchemy.Column('data', Json)
    tenant = sqlalchemy.Column(
        'tenant', sqlalchemy.String(256), nullable=False)
    status = sqlalchemy.Column('status', sqlalchemy.String(255))
    status_reason = sqlalchemy.Column('status_reason', sqlalchemy.String(255))
    stack = relationship(Stack, backref=backref('snapshot'))
