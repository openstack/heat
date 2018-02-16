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

"""SQLAlchemy models for heat data."""

import uuid

from oslo_db.sqlalchemy import models
import sqlalchemy
from sqlalchemy.ext import declarative
from sqlalchemy.orm import backref
from sqlalchemy.orm import relationship

from heat.db.sqlalchemy import types

BASE = declarative.declarative_base()


class HeatBase(models.ModelBase, models.TimestampMixin):
    """Base class for Heat Models."""
    __table_args__ = {'mysql_engine': 'InnoDB'}


class SoftDelete(object):
    deleted_at = sqlalchemy.Column(sqlalchemy.DateTime)


class StateAware(object):
    action = sqlalchemy.Column('action', sqlalchemy.String(255))
    status = sqlalchemy.Column('status', sqlalchemy.String(255))
    status_reason = sqlalchemy.Column('status_reason', sqlalchemy.Text)


class RawTemplate(BASE, HeatBase):
    """Represents an unparsed template which should be in JSON format."""

    __tablename__ = 'raw_template'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    template = sqlalchemy.Column(types.Json)
    # legacy column
    files = sqlalchemy.Column(types.Json)
    # modern column, reference to raw_template_files
    files_id = sqlalchemy.Column(
        sqlalchemy.Integer(),
        sqlalchemy.ForeignKey('raw_template_files.id'))
    environment = sqlalchemy.Column('environment', types.Json)


class RawTemplateFiles(BASE, HeatBase):
    """Where template files json dicts are stored."""
    __tablename__ = 'raw_template_files'
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    files = sqlalchemy.Column(types.Json)


class StackTag(BASE, HeatBase):
    """Key/value store of arbitrary stack tags."""

    __tablename__ = 'stack_tag'

    id = sqlalchemy.Column('id',
                           sqlalchemy.Integer,
                           primary_key=True,
                           nullable=False)
    tag = sqlalchemy.Column('tag', sqlalchemy.Unicode(80))
    stack_id = sqlalchemy.Column('stack_id',
                                 sqlalchemy.String(36),
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)


class SyncPoint(BASE, HeatBase):
    """Represents a syncpoint for a stack that is being worked on."""

    __tablename__ = 'sync_point'
    __table_args__ = (
        sqlalchemy.PrimaryKeyConstraint('entity_id',
                                        'traversal_id',
                                        'is_update'),
        sqlalchemy.ForeignKeyConstraint(['stack_id'], ['stack.id'])
    )

    entity_id = sqlalchemy.Column(sqlalchemy.String(36))
    traversal_id = sqlalchemy.Column(sqlalchemy.String(36))
    is_update = sqlalchemy.Column(sqlalchemy.Boolean)
    # integer field for atomic update operations
    atomic_key = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
                                 nullable=False)
    input_data = sqlalchemy.Column(types.Json)


class Stack(BASE, HeatBase, SoftDelete, StateAware):
    """Represents a stack created by the heat engine."""

    __tablename__ = 'stack'
    __table_args__ = (
        sqlalchemy.Index('ix_stack_name', 'name', mysql_length=255),
        sqlalchemy.Index('ix_stack_tenant', 'tenant', mysql_length=255),
    )

    id = sqlalchemy.Column(sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    name = sqlalchemy.Column(sqlalchemy.String(255))
    raw_template_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('raw_template.id'),
        nullable=False)
    raw_template = relationship(RawTemplate, backref=backref('stack'),
                                foreign_keys=[raw_template_id])
    prev_raw_template_id = sqlalchemy.Column(
        'prev_raw_template_id',
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('raw_template.id'))
    prev_raw_template = relationship(RawTemplate,
                                     foreign_keys=[prev_raw_template_id])
    username = sqlalchemy.Column(sqlalchemy.String(256))
    tenant = sqlalchemy.Column(sqlalchemy.String(256))
    user_creds_id = sqlalchemy.Column(
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('user_creds.id'))
    owner_id = sqlalchemy.Column(sqlalchemy.String(36), index=True)
    parent_resource_name = sqlalchemy.Column(sqlalchemy.String(255))
    timeout = sqlalchemy.Column(sqlalchemy.Integer)
    disable_rollback = sqlalchemy.Column(sqlalchemy.Boolean, nullable=False)
    stack_user_project_id = sqlalchemy.Column(sqlalchemy.String(64))
    backup = sqlalchemy.Column('backup', sqlalchemy.Boolean)
    nested_depth = sqlalchemy.Column('nested_depth', sqlalchemy.Integer)
    convergence = sqlalchemy.Column('convergence', sqlalchemy.Boolean)
    tags = relationship(StackTag, cascade="all,delete",
                        backref=backref('stack'))
    current_traversal = sqlalchemy.Column('current_traversal',
                                          sqlalchemy.String(36))
    current_deps = sqlalchemy.Column('current_deps', types.Json)

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
    """Represents user credentials.

    Also, mirrors the 'context' handed in by wsgi.
    """

    __tablename__ = 'user_creds'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    username = sqlalchemy.Column(sqlalchemy.String(255))
    password = sqlalchemy.Column(sqlalchemy.String(255))
    region_name = sqlalchemy.Column(sqlalchemy.String(255))
    decrypt_method = sqlalchemy.Column(sqlalchemy.String(64))
    tenant = sqlalchemy.Column(sqlalchemy.String(1024))
    auth_url = sqlalchemy.Column(sqlalchemy.Text)
    tenant_id = sqlalchemy.Column(sqlalchemy.String(256))
    trust_id = sqlalchemy.Column(sqlalchemy.String(255))
    trustor_user_id = sqlalchemy.Column(sqlalchemy.String(64))
    stack = relationship(Stack, backref=backref('user_creds'),
                         cascade_backrefs=False)


class ResourcePropertiesData(BASE, HeatBase):
    """Represents resource properties data, current or older"""

    __tablename__ = 'resource_properties_data'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    data = sqlalchemy.Column('data', types.Json)
    encrypted = sqlalchemy.Column('encrypted', sqlalchemy.Boolean)


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
    rsrc_prop_data_id = sqlalchemy.Column(sqlalchemy.Integer,
                                          sqlalchemy.ForeignKey(
                                              'resource_properties_data.id'))
    rsrc_prop_data = relationship(ResourcePropertiesData,
                                  backref=backref('event'))
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
    value = sqlalchemy.Column('value', sqlalchemy.Text)
    redact = sqlalchemy.Column('redact', sqlalchemy.Boolean)
    decrypt_method = sqlalchemy.Column(sqlalchemy.String(64))
    resource_id = sqlalchemy.Column(
        'resource_id', sqlalchemy.Integer,
        sqlalchemy.ForeignKey(column='resource.id', name='fk_resource_id',
                              ondelete='CASCADE'),
        nullable=False)


class Resource(BASE, HeatBase, StateAware):
    """Represents a resource created by the heat engine."""

    __tablename__ = 'resource'

    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    uuid = sqlalchemy.Column(sqlalchemy.String(36),
                             default=lambda: str(uuid.uuid4()),
                             unique=True)
    name = sqlalchemy.Column('name', sqlalchemy.String(255))
    physical_resource_id = sqlalchemy.Column('nova_instance',
                                             sqlalchemy.String(255))
    # odd name as "metadata" is reserved
    rsrc_metadata = sqlalchemy.Column('rsrc_metadata', types.Json)

    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    stack = relationship(Stack, backref=backref('resources'))
    root_stack_id = sqlalchemy.Column(sqlalchemy.String(36), index=True)
    data = relationship(ResourceData,
                        cascade="all",
                        passive_deletes=True,
                        backref=backref('resource'))
    rsrc_prop_data_id = sqlalchemy.Column(sqlalchemy.Integer,
                                          sqlalchemy.ForeignKey(
                                              'resource_properties_data.id'))
    rsrc_prop_data = relationship(ResourcePropertiesData,
                                  foreign_keys=[rsrc_prop_data_id])
    attr_data_id = sqlalchemy.Column(sqlalchemy.Integer,
                                     sqlalchemy.ForeignKey(
                                         'resource_properties_data.id'))
    attr_data = relationship(ResourcePropertiesData,
                             foreign_keys=[attr_data_id])

    # Override timestamp column to store the correct value: it should be the
    # time the create/update call was issued, not the time the DB entry is
    # created/modified. (bug #1193269)
    updated_at = sqlalchemy.Column(sqlalchemy.DateTime)
    properties_data = sqlalchemy.Column('properties_data', types.Json)
    properties_data_encrypted = sqlalchemy.Column('properties_data_encrypted',
                                                  sqlalchemy.Boolean)
    engine_id = sqlalchemy.Column(sqlalchemy.String(36))
    atomic_key = sqlalchemy.Column(sqlalchemy.Integer)

    needed_by = sqlalchemy.Column('needed_by', types.List)
    requires = sqlalchemy.Column('requires', types.List)
    replaces = sqlalchemy.Column('replaces', sqlalchemy.Integer,
                                 default=None)
    replaced_by = sqlalchemy.Column('replaced_by', sqlalchemy.Integer,
                                    default=None)
    current_template_id = sqlalchemy.Column(
        'current_template_id',
        sqlalchemy.Integer,
        sqlalchemy.ForeignKey('raw_template.id'))


class SoftwareConfig(BASE, HeatBase):
    """Represents a software configuration resource.

    Represents a software configuration resource to be applied to one or more
    servers.
    """

    __tablename__ = 'software_config'

    id = sqlalchemy.Column('id', sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    name = sqlalchemy.Column('name', sqlalchemy.String(255))
    group = sqlalchemy.Column('group', sqlalchemy.String(255))
    config = sqlalchemy.Column('config', types.Json)
    tenant = sqlalchemy.Column(
        'tenant', sqlalchemy.String(64), nullable=False, index=True)


class SoftwareDeployment(BASE, HeatBase, StateAware):
    """Represents a software deployment resource.

    Represents applying a software configuration resource to a single server
    resource.
    """

    __tablename__ = 'software_deployment'
    __table_args__ = (
        sqlalchemy.Index('ix_software_deployment_created_at', 'created_at'),)

    id = sqlalchemy.Column('id', sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    config_id = sqlalchemy.Column(
        'config_id',
        sqlalchemy.String(36),
        sqlalchemy.ForeignKey('software_config.id'),
        nullable=False)
    config = relationship(SoftwareConfig, backref=backref('deployments'))
    server_id = sqlalchemy.Column('server_id', sqlalchemy.String(36),
                                  nullable=False, index=True)
    input_values = sqlalchemy.Column('input_values', types.Json)
    output_values = sqlalchemy.Column('output_values', types.Json)
    tenant = sqlalchemy.Column(
        'tenant', sqlalchemy.String(64), nullable=False, index=True)
    stack_user_project_id = sqlalchemy.Column(sqlalchemy.String(64))
    updated_at = sqlalchemy.Column(sqlalchemy.DateTime)


class Snapshot(BASE, HeatBase):

    __tablename__ = 'snapshot'

    id = sqlalchemy.Column('id', sqlalchemy.String(36), primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    stack_id = sqlalchemy.Column(sqlalchemy.String(36),
                                 sqlalchemy.ForeignKey('stack.id'),
                                 nullable=False)
    name = sqlalchemy.Column('name', sqlalchemy.String(255))
    data = sqlalchemy.Column('data', types.Json)
    tenant = sqlalchemy.Column(
        'tenant', sqlalchemy.String(64), nullable=False, index=True)
    status = sqlalchemy.Column('status', sqlalchemy.String(255))
    status_reason = sqlalchemy.Column('status_reason', sqlalchemy.String(255))
    stack = relationship(Stack, backref=backref('snapshot'))


class Service(BASE, HeatBase, SoftDelete):

    __tablename__ = 'service'

    id = sqlalchemy.Column('id',
                           sqlalchemy.String(36),
                           primary_key=True,
                           default=lambda: str(uuid.uuid4()))
    engine_id = sqlalchemy.Column('engine_id',
                                  sqlalchemy.String(36),
                                  nullable=False)
    host = sqlalchemy.Column('host',
                             sqlalchemy.String(255),
                             nullable=False)
    hostname = sqlalchemy.Column('hostname',
                                 sqlalchemy.String(255),
                                 nullable=False)
    binary = sqlalchemy.Column('binary',
                               sqlalchemy.String(255),
                               nullable=False)
    topic = sqlalchemy.Column('topic',
                              sqlalchemy.String(255),
                              nullable=False)
    report_interval = sqlalchemy.Column('report_interval',
                                        sqlalchemy.Integer,
                                        nullable=False)
