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
import eventlet
from eventlet.support import greenlets as greenlet

from heat.engine import event
from heat.common import exception
from heat.openstack.common import excutils
from heat.db import api as db_api
from heat.common import identifier
from heat.engine import timestamp
from heat.engine.properties import Properties

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


_resource_classes = {}


def get_types():
    '''Return an iterator over the list of valid resource types'''
    return iter(_resource_classes)


def get_class(resource_type):
    '''Return the Resource class for a given resource type'''
    cls = _resource_classes.get(resource_type)
    if cls is None:
        msg = "Unknown resource Type : %s" % resource_type
        raise exception.StackValidationFailed(message=msg)
    else:
        return cls


def _register_class(resource_type, resource_class):
    logger.info(_('Registering resource type %s') % resource_type)
    if resource_type in _resource_classes:
        logger.warning(_('Replacing existing resource type %s') %
                       resource_type)

    _resource_classes[resource_type] = resource_class


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
            raise exception.ResourceNotAvailable(resource_name=resource.name)
        rs = db_api.resource_get(resource.stack.context, resource.id)
        rs.update_and_save({'rsrc_metadata': metadata})


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

    created_time = timestamp.Timestamp(db_api.resource_get, 'created_at')
    updated_time = timestamp.Timestamp(db_api.resource_get, 'updated_at')

    metadata = Metadata()

    # Resource implementation set this to the subset of template keys
    # which are supported for handle_update, used by update_template_diff
    update_allowed_keys = ()

    # Resource implementation set this to the subset of resource properties
    # supported for handle_update, used by update_template_diff_properties
    update_allowed_properties = ()

    def __new__(cls, name, json, stack):
        '''Create a new Resource of the appropriate class for its type.'''

        if cls != Resource:
            # Call is already for a subclass, so pass it through
            return super(Resource, cls).__new__(cls)

        # Select the correct subclass to instantiate
        ResourceClass = get_class(json['Type'])
        return ResourceClass(name, json, stack)

    def __init__(self, name, json_snippet, stack):
        if '/' in name:
            raise ValueError(_('Resource name may not contain "/"'))

        self.stack = stack
        self.context = stack.context
        self.name = name
        self.json_snippet = json_snippet
        self.t = stack.resolve_static_data(json_snippet)
        self.cached_t = None
        self.properties = Properties(self.properties_schema,
                                     self.t.get('Properties', {}),
                                     self.stack.resolve_runtime_data,
                                     self.name)

        resource = db_api.resource_get_by_name_and_stack(self.context,
                                                         name, stack.id)
        if resource:
            self.resource_id = resource.nova_instance
            self.state = resource.state
            self.state_description = resource.state_description
            self.id = resource.id
        else:
            self.resource_id = None
            self.state = None
            self.state_description = ''
            self.id = None

    def __eq__(self, other):
        '''Allow == comparison of two resources'''
        # For the purposes of comparison, we declare two resource objects
        # equal if their names and parsed_templates are the same
        if isinstance(other, Resource):
            return (self.name == other.name) and (
                self.parsed_template() == other.parsed_template())
        return NotImplemented

    def __ne__(self, other):
        '''Allow != comparison of two resources'''
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def type(self):
        return self.t['Type']

    def identifier(self):
        '''Return an identifier for this resource'''
        return identifier.ResourceIdentifier(resource_name=self.name,
                                             **self.stack.identifier())

    def parsed_template(self, section=None, default={}, cached=False):
        '''
        Return the parsed template data for the resource. May be limited to
        only one section of the data, in which case a default value may also
        be supplied.
        '''
        if cached and self.cached_t:
            t = self.cached_t
        else:
            t = self.t
        if section is None:
            template = t
        else:
            template = t.get(section, default)
        return self.stack.resolve_runtime_data(template)

    def cache_template(self):
        '''
        make a cache of the resource's parsed template
        this can then be used via parsed_template(cached=True)
        '''
        self.cached_t = self.stack.resolve_runtime_data(self.t)

    def update_template_diff(self, json_snippet=None):
        '''
        Returns the difference between json_template and self.t
        If something has been removed in json_snippet which exists
        in self.t we set it to None.  If any keys have changed which
        are not in update_allowed_keys, raises NotImplementedError
        '''
        update_allowed_set = set(self.update_allowed_keys)

        # Create a set containing the keys in both current and update template
        current_template = self.parsed_template(cached=True)

        template_keys = set(current_template.keys())
        new_template = self.stack.resolve_runtime_data(json_snippet)
        template_keys.update(set(new_template.keys()))

        # Create a set of keys which differ (or are missing/added)
        changed_keys_set = set([k for k in template_keys
                               if current_template.get(k) !=
                               new_template.get(k)])

        if not changed_keys_set.issubset(update_allowed_set):
            badkeys = changed_keys_set - update_allowed_set
            raise NotImplementedError("Cannot update keys %s for %s" %
                                      (badkeys, self.name))

        return dict((k, new_template.get(k)) for k in changed_keys_set)

    def update_template_diff_properties(self, json_snippet=None):
        '''
        Returns the changed Properties between json_template and self.t
        If a property has been removed in json_snippet which exists
        in self.t we set it to None.  If any properties have changed which
        are not in update_allowed_properties, raises NotImplementedError
        '''
        update_allowed_set = set(self.update_allowed_properties)

        # Create a set containing the keys in both current and update template
        tmpl = self.parsed_template(cached=True)
        current_properties = tmpl.get('Properties', {})

        template_properties = set(current_properties.keys())
        updated_properties = json_snippet.get('Properties', {})
        template_properties.update(set(updated_properties.keys()))

        # Create a set of keys which differ (or are missing/added)
        changed_properties_set = set(k for k in template_properties
                                     if current_properties.get(k) !=
                                     updated_properties.get(k))

        if not changed_properties_set.issubset(update_allowed_set):
            badkeys = changed_properties_set - update_allowed_set
            raise NotImplementedError("Cannot update properties %s for %s" %
                                      (badkeys, self.name))

        return dict((k, updated_properties.get(k))
                    for k in changed_properties_set)

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
        return self.stack.clients.keystone()

    def nova(self, service_type='compute'):
        return self.stack.clients.nova(service_type)

    def swift(self):
        return self.stack.clients.swift()

    def quantum(self):
        return self.stack.clients.quantum()

    def cinder(self):
        return self.stack.clients.cinder()

    def create(self):
        '''
        Create the resource. Subclasses should provide a handle_create() method
        to customise creation.
        '''
        assert self.state is None, 'Resource create requested in invalid state'

        logger.info('creating %s' % str(self))

        # Re-resolve the template, since if the resource Ref's
        # the AWS::StackId pseudo parameter, it will change after
        # the parser.Stack is stored (which is after the resources
        # are __init__'d, but before they are create()'d)
        self.t = self.stack.resolve_static_data(self.json_snippet)
        self.properties = Properties(self.properties_schema,
                                     self.t.get('Properties', {}),
                                     self.stack.resolve_runtime_data,
                                     self.name)
        try:
            self.properties.validate()
            self.state_set(self.CREATE_IN_PROGRESS)
            create_data = None
            if callable(getattr(self, 'handle_create', None)):
                create_data = self.handle_create()
            while not self.check_active(create_data):
                eventlet.sleep(1)
        except greenlet.GreenletExit:
            # Older versions of greenlet erroneously had GreenletExit inherit
            # from Exception instead of BaseException
            with excutils.save_and_reraise_exception():
                try:
                    self.state_set(self.CREATE_FAILED, 'Creation aborted')
                except Exception:
                    logger.exception('Error marking resource as failed')
        except Exception as ex:
            logger.exception('create %s', str(self))
            failure = exception.ResourceFailure(ex)
            self.state_set(self.CREATE_FAILED, str(failure))
            raise failure
        except:
            with excutils.save_and_reraise_exception():
                try:
                    self.state_set(self.CREATE_FAILED, 'Creation aborted')
                except Exception:
                    logger.exception('Error marking resource as failed')
        else:
            self.state_set(self.CREATE_COMPLETE)

    def check_active(self, create_data):
        '''
        Check if the resource is active (ready to move to the CREATE_COMPLETE
        state). By default this happens as soon as the handle_create() method
        has completed successfully, but subclasses may customise this by
        overriding this function. The return value of handle_create() is
        passed in to this function each time it is called.
        '''
        return True

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
            properties = Properties(self.properties_schema,
                                    json_snippet.get('Properties', {}),
                                    self.stack.resolve_runtime_data,
                                    self.name)
            properties.validate()
            if callable(getattr(self, 'handle_update', None)):
                result = self.handle_update(json_snippet)
        except Exception as ex:
            logger.exception('update %s : %s' % (str(self), str(ex)))
            self.state_set(self.UPDATE_FAILED, str(ex))
            return str(ex) or "Error : %s" % type(ex)
        else:
            # If resource was updated (with or without interruption),
            # then we set the resource to UPDATE_COMPLETE
            if not result == self.UPDATE_REPLACE:
                self.t = self.stack.resolve_static_data(json_snippet)
                self.state_set(self.UPDATE_COMPLETE)
            return result

    def physical_resource_name(self):
        return '%s.%s' % (self.stack.name, self.name)

    def physical_resource_name_find(self, resource_name):
        if resource_name in self.stack:
            return '%s.%s' % (self.stack.name, resource_name)
        else:
            raise IndexError('no such resource')

    def validate(self):
        logger.info('Validating %s' % str(self))

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
        # No need to delete if the resource has never been created
        if self.state is None:
            return

        logger.info('deleting %s (inst:%s db_id:%s)' %
                    (str(self), self.resource_id, str(self.id)))
        self.state_set(self.DELETE_IN_PROGRESS)

        try:
            if callable(getattr(self, 'handle_delete', None)):
                self.handle_delete()
        except Exception as ex:
            logger.exception('Delete %s', str(self))
            self.state_set(self.DELETE_FAILED, str(ex))
            return str(ex) or "Error : %s" % type(ex)

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
            return str(ex) or "Error : %s" % type(ex)

        self.id = None

    def resource_id_set(self, inst):
        self.resource_id = inst
        if self.id is not None:
            try:
                rs = db_api.resource_get(self.context, self.id)
                rs.update_and_save({'nova_instance': self.resource_id})
            except Exception as ex:
                logger.warn('db error %s' % str(ex))

    def _store(self):
        '''Create the resource in the database'''
        try:
            rs = {'state': self.state,
                  'stack_id': self.stack.id,
                  'nova_instance': self.resource_id,
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
        ev = event.Event(self.context, self.stack, self,
                         new_state, reason,
                         self.resource_id, self.properties)

        try:
            ev.store()
        except Exception as ex:
            logger.error('DB error %s' % str(ex))

    def _store_or_update(self, new_state, reason):
        self.state = new_state
        self.state_description = reason

        if self.id is not None:
            try:
                rs = db_api.resource_get(self.context, self.id)
                rs.update_and_save({'state': self.state,
                                    'state_description': reason,
                                    'nova_instance': self.resource_id})

                self.stack.updated_time = datetime.utcnow()
            except Exception as ex:
                logger.error('DB error %s' % str(ex))

        # store resource in DB on transition to CREATE_IN_PROGRESS
        # all other transistions (other than to DELETE_COMPLETE)
        # should be handled by the update_and_save above..
        elif new_state == self.CREATE_IN_PROGRESS:
            self._store()

    def state_set(self, new_state, reason="state changed"):
        old_state = self.state
        self._store_or_update(new_state, reason)

        if new_state != old_state:
            self._add_event(new_state, reason)

    def FnGetRefId(self):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/\
        intrinsic-function-reference-ref.html
        '''
        if self.resource_id is not None:
            return unicode(self.resource_id)
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

    def handle_update(self, json_snippet=None):
        raise NotImplementedError("Update not implemented for Resource %s"
                                  % type(self))

    def metadata_update(self, new_metadata=None):
        '''
        No-op for resources which don't explicitly override this method
        '''
        if new_metadata:
            logger.warning("Resource %s does not implement metadata update" %
                           self.name)
