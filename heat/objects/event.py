# Copyright 2014 Intel Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Event object."""

from oslo_log import log as logging
from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from heat.common import identifier
from heat.db.sqlalchemy import api as db_api
from heat.objects import base as heat_base
from heat.objects import resource_properties_data as rpd

LOG = logging.getLogger(__name__)


class Event(
        heat_base.HeatObject,
        base.VersionedObjectDictCompat,
):
    fields = {
        'id': fields.IntegerField(),
        'stack_id': fields.StringField(),
        'uuid': fields.StringField(),
        'resource_action': fields.StringField(nullable=True),
        'resource_status': fields.StringField(nullable=True),
        'resource_name': fields.StringField(nullable=True),
        'physical_resource_id': fields.StringField(nullable=True),
        'resource_status_reason': fields.StringField(nullable=True),
        'resource_type': fields.StringField(nullable=True),
        'rsrc_prop_data_id': fields.ObjectField(
            fields.IntegerField(nullable=True)),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, event, db_event):
        event._resource_properties = None
        for field in event.fields:
            if field == 'resource_status_reason':
                # this works whether db_event is a dict or db ref
                event[field] = db_event['_resource_status_reason']
            else:
                event[field] = db_event[field]
        if db_event['rsrc_prop_data_id'] is None:
            event._resource_properties = db_event['resource_properties'] or {}
        else:
            if hasattr(db_event, '__dict__'):
                rpd_obj = db_event.__dict__.get('rsrc_prop_data')
            elif hasattr(db_event, 'rsrc_prop_data'):
                rpd_obj = db_event['rsrc_prop_data']
            else:
                rpd_obj = None
            if rpd_obj is not None:
                # Object is already eager loaded
                rpd_obj = (
                    rpd.ResourcePropertiesData._from_db_object(
                        rpd.ResourcePropertiesData(),
                        context,
                        rpd_obj))
                event._resource_properties = rpd_obj.data
        event._context = context
        event.obj_reset_changes()
        return event

    @property
    def resource_properties(self):
        if self._resource_properties is None:
            LOG.info('rsrc_prop_data lazy load')
            rpd_obj = rpd.ResourcePropertiesData.get_by_id(
                self._context, self.rsrc_prop_data_id)
            self._resource_properties = rpd_obj.data or {}
        return self._resource_properties

    @classmethod
    def get_all_by_tenant(cls, context, **kwargs):
        return [cls._from_db_object(context, cls(), db_event)
                for db_event in db_api.event_get_all_by_tenant(context,
                                                               **kwargs)]

    @classmethod
    def get_all_by_stack(cls, context, stack_id, **kwargs):
        return [cls._from_db_object(context, cls(), db_event)
                for db_event in db_api.event_get_all_by_stack(context,
                                                              stack_id,
                                                              **kwargs)]

    @classmethod
    def count_all_by_stack(cls, context, stack_id):
        return db_api.event_count_all_by_stack(context, stack_id)

    @classmethod
    def create(cls, context, values):
        # Using dict() allows us to be done with the sqlalchemy/model
        # layer in one call, rather than hitting that layer for every
        # field in _from_db_object().
        return cls._from_db_object(context, cls(context=context),
                                   dict(db_api.event_create(context, values)))

    def identifier(self, stack_identifier):
        """Return a unique identifier for the event."""

        res_id = identifier.ResourceIdentifier(
            resource_name=self.resource_name, **stack_identifier)

        return identifier.EventIdentifier(event_id=str(self.uuid), **res_id)
