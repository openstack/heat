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

import base64
from datetime import datetime

from novaclient.v1_1 import client as nc
from keystoneclient.v2_0 import client as kc

from heat.common import exception
from heat.common import config
from heat.db import api as db_api
from heat.engine import checkeddict
from heat.engine import auth

from heat.openstack.common import log as logging
from heat.openstack.common import cfg

logger = logging.getLogger('heat.engine.resources')


class Metadata(object):
    '''
    A descriptor for accessing the metadata of a resource while ensuring the
    most up-to-date data is always obtained from the database.
    '''

    def __get__(self, resource, resource_class):
        '''Return the metadata for the owning resource.'''
        if resource is None:
            return None
        if resource.id is None:
            return resource.parsed_template('Metadata')
        rs = db_api.resource_get(resource.stack.context, resource.id)
        rs.refresh(attrs=['rsrc_metadata'])
        return rs.rsrc_metadata

    def __set__(self, resource, metadata):
        '''Update the metadata for the owning resource.'''
        if resource.id is None:
            raise AttributeError("Resource has not yet been created")
        rs = db_api.resource_get(resource.stack.context, resource.id)
        rs.update_and_save({'rsrc_metadata': metadata})

    @staticmethod
    def server():
        '''
        Get the address of the currently registered metadata server. Return
        None if no server is registered.
        '''
        try:
            return cfg.CONF.heat_metadata_server_url
        except AttributeError:
            return None


class Timestamp(object):
    '''
    A descriptor for fetching an up-to-date timestamp from the database.
    '''

    def __init__(self, db_fetch, attribute):
        '''
        Initialise with a function to fetch the database representation of an
        object (given a context and ID) and the name of the attribute to
        retrieve.
        '''
        self.db_fetch = db_fetch
        self.attribute = attribute

    def __get__(self, obj, obj_class):
        '''
        Get the latest data from the database for the given object and class.
        '''
        if obj is None or obj.id is None:
            return None

        o = self.db_fetch(obj.context, obj.id)
        o.refresh(attrs=[self.attribute])
        return getattr(o, self.attribute)

    def __set__(self, obj, timestamp):
        '''Update the timestamp for the given object.'''
        if obj.id is None:
            raise AttributeError("%s has not yet been created" % str(obj))
        o = self.db_fetch(obj.context, obj.id)
        o.update_and_save({self.attribute: timestamp})


class Resource(object):
    # Status strings
    CREATE_IN_PROGRESS = 'IN_PROGRESS'
    CREATE_FAILED = 'CREATE_FAILED'
    CREATE_COMPLETE = 'CREATE_COMPLETE'
    DELETE_IN_PROGRESS = 'DELETE_IN_PROGRESS'
    DELETE_FAILED = 'DELETE_FAILED'
    DELETE_COMPLETE = 'DELETE_COMPLETE'
    UPDATE_IN_PROGRESS = 'UPDATE_IN_PROGRESS'
    UPDATE_FAILED = 'UPDATE_FAILED'
    UPDATE_COMPLETE = 'UPDATE_COMPLETE'

    # Status values, returned from subclasses to indicate update method
    UPDATE_REPLACE = 'UPDATE_REPLACE'
    UPDATE_INTERRUPTION = 'UPDATE_INTERRUPTION'
    UPDATE_NO_INTERRUPTION = 'UPDATE_NO_INTERRUPTION'
    UPDATE_NOT_IMPLEMENTED = 'UPDATE_NOT_IMPLEMENTED'

    # If True, this resource must be created before it can be referenced.
    strict_dependency = True

    created_time = Timestamp(db_api.resource_get, 'created_at')
    updated_time = Timestamp(db_api.resource_get, 'updated_at')

    metadata = Metadata()

    def __new__(cls, name, json, stack):
        '''Create a new Resource of the appropriate class for its type.'''

        if cls != Resource:
            # Call is already for a subclass, so pass it through
            return super(Resource, cls).__new__(cls, name, json, stack)

        # Select the correct subclass to instantiate
        import resource_types
        ResourceClass = resource_types.getClass(json['Type'])
        return ResourceClass(name, json, stack)

    def __init__(self, name, json_snippet, stack):
        self.references = []
        self.stack = stack
        self.context = stack.context
        self.name = name
        self.t = stack.resolve_static_data(json_snippet)
        self.properties = checkeddict.Properties(name, self.properties_schema)

        resource = db_api.resource_get_by_name_and_stack(self.context,
                                                         name, stack.id)
        if resource:
            self.instance_id = resource.nova_instance
            self.state = resource.state
            self.state_description = resource.state_description
            self.id = resource.id
        else:
            self.instance_id = None
            self.state = None
            self.state_description = ''
            self.id = None
        self._nova = {}
        self._keystone = None

    def __eq__(self, other):
        '''Allow == comparison of two resources'''
        # For the purposes of comparison, we declare two resource objects
        # equal if their parsed_templates are the same
        if isinstance(other, Resource):
            return self.parsed_template() == other.parsed_template()
        return NotImplemented

    def __ne__(self, other):
        '''Allow != comparison of two resources'''
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def parsed_template(self, section=None, default={}):
        '''
        Return the parsed template data for the resource. May be limited to
        only one section of the data, in which case a default value may also
        be supplied.
        '''
        if section is None:
            template = self.t
        else:
            template = self.t.get(section, default)
        return self.stack.resolve_runtime_data(template)

    def __str__(self):
        return '%s "%s"' % (self.__class__.__name__, self.name)

    def _add_dependencies(self, deps, fragment):
        if isinstance(fragment, dict):
            for key, value in fragment.items():
                if key in ('DependsOn', 'Ref'):
                    target = self.stack.resources[value]
                    if key == 'DependsOn' or target.strict_dependency:
                        deps += (self, target)
                elif key != 'Fn::GetAtt':
                    self._add_dependencies(deps, value)
        elif isinstance(fragment, list):
            for item in fragment:
                self._add_dependencies(deps, item)

    def add_dependencies(self, deps):
        self._add_dependencies(deps, self.t)
        deps += (self, None)

    def keystone(self):
        if self._keystone:
            return self._keystone

        con = self.context
        self._keystone = kc.Client(username=con.username,
                                   password=con.password,
                                   tenant_name=con.tenant,
                                   auth_url=con.auth_url)
        return self._keystone

    def nova(self, service_type='compute'):
        if service_type in self._nova:
            return self._nova[service_type]

        self._nova[service_type] = auth.authenticate(self.context,
                                                     service_type=service_type,
                                                     service_name=None)
        return self._nova[service_type]

    def calculate_properties(self):
        for p, v in self.parsed_template('Properties').items():
            self.properties[p] = v

    def create(self):
        '''
        Create the resource. Subclasses should provide a handle_create() method
        to customise creation.
        '''
        if self.state in (self.CREATE_IN_PROGRESS, self.CREATE_COMPLETE):
            return 'Resource creation already requested'

        logger.info('creating %s' % str(self))

        try:
            self.calculate_properties()
            self.properties.validate()
            self.state_set(self.CREATE_IN_PROGRESS)
            if callable(getattr(self, 'handle_create', None)):
                self.handle_create()
        except Exception as ex:
            logger.exception('create %s', str(self))
            self.state_set(self.CREATE_FAILED, str(ex))
            return str(ex)
        else:
            self.state_set(self.CREATE_COMPLETE)

    def update(self, json_snippet=None):
        '''
        update the resource. Subclasses should provide a handle_update() method
        to customise update, the base-class handle_update will fail by default.
        '''
        if self.state in (self.CREATE_IN_PROGRESS, self.UPDATE_IN_PROGRESS):
            return 'Resource update already requested'

        if not json_snippet:
            return 'Must specify json snippet for resource update!'

        logger.info('updating %s' % str(self))

        result = self.UPDATE_NOT_IMPLEMENTED
        try:
            self.state_set(self.UPDATE_IN_PROGRESS)
            self.t = self.stack.resolve_static_data(json_snippet)
            self.properties = checkeddict.Properties(self.name,
                                                     self.properties_schema)
            self.calculate_properties()
            self.properties.validate()
            if callable(getattr(self, 'handle_update', None)):
                result = self.handle_update()
        except Exception as ex:
            logger.exception('update %s : %s' % (str(self), str(ex)))
            self.state_set(self.UPDATE_FAILED, str(ex))
            return str(ex)
        else:
            # If resource was updated (with or without interruption),
            # then we set the resource to UPDATE_COMPLETE
            if not result == self.UPDATE_REPLACE:
                self.state_set(self.UPDATE_COMPLETE)
            return result

    def validate(self):
        logger.info('Validating %s' % str(self))

    def validate(self):
        logger.info('Validating %s' % str(self))

        try:
            self.calculate_properties()
        except ValueError as ex:
                return str(ex)
        return self.properties.validate()

    def delete(self):
        '''
        Delete the resource. Subclasses should provide a handle_delete() method
        to customise deletion.
        '''
        if self.state == self.DELETE_COMPLETE:
            return
        if self.state == self.DELETE_IN_PROGRESS:
            return 'Resource deletion already in progress'

        logger.info('deleting %s (inst:%s db_id:%s)' %
                    (str(self), self.instance_id, str(self.id)))
        self.state_set(self.DELETE_IN_PROGRESS)

        try:
            if callable(getattr(self, 'handle_delete', None)):
                self.handle_delete()
        except Exception as ex:
            logger.exception('Delete %s', str(self))
            self.state_set(self.DELETE_FAILED, str(ex))
            return str(ex)

        self.state_set(self.DELETE_COMPLETE)

    def destroy(self):
        '''
        Delete the resource and remove it from the database.
        '''
        result = self.delete()
        if result:
            return result

        if self.id is None:
            return

        try:
            db_api.resource_get(self.context, self.id).delete()
        except exception.NotFound:
            # Don't fail on delete if the db entry has
            # not been created yet.
            pass
        except Exception as ex:
            logger.exception('Delete %s from DB' % str(self))
            return str(ex)

    def instance_id_set(self, inst):
        self.instance_id = inst
        if self.id is not None:
            try:
                rs = db_api.resource_get(self.stack.context, self.id)
                rs.update_and_save({'nova_instance': self.instance_id})
            except Exception as ex:
                logger.warn('db error %s' % str(ex))

    def _store(self):
        '''Create the resource in the database'''
        try:
            rs = {'state': self.state,
                  'stack_id': self.stack.id,
                  'nova_instance': self.instance_id,
                  'name': self.name,
                  'rsrc_metadata': self.metadata,
                  'stack_name': self.stack.name}

            new_rs = db_api.resource_create(self.context, rs)
            self.id = new_rs.id

            self.stack.updated_time = datetime.utcnow()

        except Exception as ex:
            logger.error('DB error %s' % str(ex))

    def _add_event(self, new_state, reason):
        '''Add a state change event to the database'''
        self.calculate_properties()
        ev = {'logical_resource_id': self.name,
              'physical_resource_id': self.instance_id,
              'stack_id': self.stack.id,
              'stack_name': self.stack.name,
              'resource_status': new_state,
              'name': new_state,
              'resource_status_reason': reason,
              'resource_type': self.t['Type'],
              'resource_properties': dict(self.properties)}
        try:
            db_api.event_create(self.context, ev)
        except Exception as ex:
            logger.error('DB error %s' % str(ex))

    def state_set(self, new_state, reason="state changed"):
        self.state, old_state = new_state, self.state
        self.state_description = reason

        if self.id is not None:
            try:
                rs = db_api.resource_get(self.context, self.id)
                rs.update_and_save({'state': self.state,
                                    'state_description': reason,
                                    'nova_instance': self.instance_id})

                self.stack.updated_time = datetime.utcnow()
            except Exception as ex:
                logger.error('DB error %s' % str(ex))

        elif new_state in (self.CREATE_COMPLETE, self.CREATE_FAILED):
            self._store()

        if new_state != old_state:
            self._add_event(new_state, reason)

    def FnGetRefId(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/\
        intrinsic-function-reference-ref.html
        '''
        if self.instance_id is not None:
            return unicode(self.instance_id)
        else:
            return unicode(self.name)

    def FnGetAtt(self, key):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/\
        intrinsic-function-reference-getatt.html
        '''
        return unicode(self.name)

    def FnBase64(self, data):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/\
            intrinsic-function-reference-base64.html
        '''
        return base64.b64encode(data)

    def handle_update(self):
        raise NotImplementedError("Update not implemented for Resource %s"
                                  % type(self))


class GenericResource(Resource):
    properties_schema = {}

    def handle_create(self):
        logger.warning('Creating generic resource (Type "%s")' %
                self.t['Type'])

    def handle_update(self):
        logger.warning('Updating generic resource (Type "%s")' %
                self.t['Type'])
