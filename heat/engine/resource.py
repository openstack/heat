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

from heat.engine import event
from heat.common import exception
from heat.openstack.common import excutils
from heat.db import api as db_api
from heat.common import identifier
from heat.common import short_id
from heat.engine import scheduler
from heat.engine import resources
from heat.engine import timestamp
# import class to avoid name collisions and ugly aliasing
from heat.engine.attributes import Attributes
from heat.engine.properties import Properties

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

logger = logging.getLogger(__name__)


def get_types():
    '''Return an iterator over the list of valid resource types.'''
    return iter(resources.global_env().get_types())


def get_class(resource_type, resource_name=None):
    '''Return the Resource class for a given resource type.'''
    return resources.global_env().get_class(resource_type, resource_name)


def _register_class(resource_type, resource_class):
    resources.global_env().register_class(resource_type, resource_class)


class UpdateReplace(Exception):
    '''
    Raised when resource update requires replacement
    '''
    _message = _("The Resource %s requires replacement.")

    def __init__(self, resource_name='Unknown',
                 message=_("The Resource %s requires replacement.")):
        try:
            msg = message % resource_name
        except TypeError:
            msg = message
        super(Exception, self).__init__(msg)


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
    ACTIONS = (INIT, CREATE, DELETE, UPDATE, ROLLBACK, SUSPEND, RESUME
               ) = ('INIT', 'CREATE', 'DELETE', 'UPDATE', 'ROLLBACK',
                    'SUSPEND', 'RESUME')

    STATUSES = (IN_PROGRESS, FAILED, COMPLETE
                ) = ('IN_PROGRESS', 'FAILED', 'COMPLETE')

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

    # Resource implementations set this to the name: description dictionary
    # that describes the appropriate resource attributes
    attributes_schema = {}

    # If True, this resource may perform authenticated API requests
    # throughout its lifecycle
    requires_deferred_auth = False

    # Limit to apply to physical_resource_name() size reduction algorithm.
    # If set to None no limit will be applied.
    physical_resource_name_limit = 255

    def __new__(cls, name, json, stack):
        '''Create a new Resource of the appropriate class for its type.'''

        if cls != Resource:
            # Call is already for a subclass, so pass it through
            return super(Resource, cls).__new__(cls)

        # Select the correct subclass to instantiate
        ResourceClass = stack.env.get_class(json['Type'],
                                            resource_name=name)
        return ResourceClass(name, json, stack)

    def __init__(self, name, json_snippet, stack):
        if '/' in name:
            raise ValueError(_('Resource name may not contain "/"'))

        self.stack = stack
        self.context = stack.context
        self.name = name
        self.json_snippet = json_snippet
        self.t = stack.resolve_static_data(json_snippet)
        self.properties = Properties(self.properties_schema,
                                     self.t.get('Properties', {}),
                                     self._resolve_runtime_data,
                                     self.name)
        self.attributes = Attributes(self.name,
                                     self.attributes_schema,
                                     self._resolve_attribute)

        resource = db_api.resource_get_by_name_and_stack(self.context,
                                                         name, stack.id)
        if resource:
            self.resource_id = resource.nova_instance
            self.action = resource.action
            self.status = resource.status
            self.status_reason = resource.status_reason
            self.id = resource.id
            self.data = resource.data
        else:
            self.resource_id = None
            # if the stack is being deleted, assume we've already been deleted
            if stack.action == stack.DELETE:
                self.action = self.DELETE
            else:
                self.action = self.INIT
            self.status = self.COMPLETE
            self.status_reason = ''
            self.id = None
            self.data = []

    def __eq__(self, other):
        '''Allow == comparison of two resources.'''
        # For the purposes of comparison, we declare two resource objects
        # equal if their names and parsed_templates are the same
        if isinstance(other, Resource):
            return (self.name == other.name) and (
                self.parsed_template() == other.parsed_template())
        return NotImplemented

    def __ne__(self, other):
        '''Allow != comparison of two resources.'''
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def type(self):
        return self.t['Type']

    def _resolve_runtime_data(self, snippet):
        return self.stack.resolve_runtime_data(snippet)

    def has_interface(self, resource_type):
        """Check to see if this resource is either mapped to resource_type
        or is a "resource_type".
        """
        if self.type() == resource_type:
            return True
        ri = self.stack.env.get_resource_info(self.type(),
                                              self.name)
        return ri.name == resource_type

    def identifier(self):
        '''Return an identifier for this resource.'''
        return identifier.ResourceIdentifier(resource_name=self.name,
                                             **self.stack.identifier())

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
        return self._resolve_runtime_data(template)

    def update_template_diff(self, after, before):
        '''
        Returns the difference between the before and after json snippets. If
        something has been removed in after which exists in before we set it to
        None. If any keys have changed which are not in update_allowed_keys,
        raises UpdateReplace if the differing keys are not in
        update_allowed_keys
        '''
        update_allowed_set = set(self.update_allowed_keys)

        # Create a set containing the keys in both current and update template
        template_keys = set(before.keys())
        template_keys.update(set(after.keys()))

        # Create a set of keys which differ (or are missing/added)
        changed_keys_set = set([k for k in template_keys
                                if before.get(k) != after.get(k)])

        if not changed_keys_set.issubset(update_allowed_set):
            badkeys = changed_keys_set - update_allowed_set
            raise UpdateReplace(self.name)

        return dict((k, after.get(k)) for k in changed_keys_set)

    def update_template_diff_properties(self, after, before):
        '''
        Returns the changed Properties between the before and after json
        snippets. If a property has been removed in after which exists in
        before we set it to None. If any properties have changed which are not
        in update_allowed_properties, raises UpdateReplace if the modified
        properties are not in the update_allowed_properties
        '''
        update_allowed_set = set(self.update_allowed_properties)

        # Create a set containing the keys in both current and update template
        current_properties = before.get('Properties', {})

        template_properties = set(current_properties.keys())
        updated_properties = after.get('Properties', {})
        template_properties.update(set(updated_properties.keys()))

        # Create a set of keys which differ (or are missing/added)
        changed_properties_set = set(k for k in template_properties
                                     if current_properties.get(k) !=
                                     updated_properties.get(k))

        if not changed_properties_set.issubset(update_allowed_set):
            raise UpdateReplace(self.name)

        return dict((k, updated_properties.get(k))
                    for k in changed_properties_set)

    def __str__(self):
        return '%s "%s"' % (self.__class__.__name__, self.name)

    def _add_dependencies(self, deps, path, fragment):
        if isinstance(fragment, dict):
            for key, value in fragment.items():
                if key in ('DependsOn', 'Ref', 'Fn::GetAtt', 'get_attr',
                           'get_resource'):
                    if key in ('Fn::GetAtt', 'get_attr'):
                        res_name, att = value
                        res_list = [res_name]
                    elif key == 'DependsOn' and isinstance(value, list):
                        res_list = value
                    else:
                        res_list = [value]

                    for res in res_list:
                        try:
                            target = self.stack[res]
                        except KeyError:
                            raise exception.InvalidTemplateReference(
                                resource=res,
                                key=path)
                        if key == 'DependsOn' or target.strict_dependency:
                            deps += (self, target)
                else:
                    self._add_dependencies(deps, '%s.%s' % (path, key), value)
        elif isinstance(fragment, list):
            for index, item in enumerate(fragment):
                self._add_dependencies(deps, '%s[%d]' % (path, index), item)

    def add_dependencies(self, deps):
        self._add_dependencies(deps, self.name, self.t)
        deps += (self, None)

    def required_by(self):
        '''
        Returns a list of names of resources which directly require this
        resource as a dependency.
        '''
        return list(
            [r.name for r in self.stack.dependencies.required_by(self)])

    def keystone(self):
        return self.stack.clients.keystone()

    def nova(self, service_type='compute'):
        return self.stack.clients.nova(service_type)

    def swift(self):
        return self.stack.clients.swift()

    def neutron(self):
        return self.stack.clients.neutron()

    def cinder(self):
        return self.stack.clients.cinder()

    def ceilometer(self):
        return self.stack.clients.ceilometer()

    def _do_action(self, action, pre_func=None):
        '''
        Perform a transition to a new state via a specified action
        action should be e.g self.CREATE, self.UPDATE etc, we set
        status based on this, the transistion is handled by calling the
        corresponding handle_* and check_*_complete functions
        Note pre_func is an optional function reference which will
        be called before the handle_<action> function

        If the resource does not declare a check_$action_complete function,
        we declare COMPLETE status as soon as the handle_$action call has
        finished, and if no handle_$action function is declared, then we do
        nothing, useful e.g if the resource requires no action for a given
        state transition
        '''
        assert action in self.ACTIONS, 'Invalid action %s' % action

        try:
            self.state_set(action, self.IN_PROGRESS)

            action_l = action.lower()
            handle = getattr(self, 'handle_%s' % action_l, None)
            check = getattr(self, 'check_%s_complete' % action_l, None)

            if callable(pre_func):
                pre_func()

            handle_data = None
            if callable(handle):
                handle_data = handle()
                yield
                if callable(check):
                    while not check(handle_data):
                        yield
        except Exception as ex:
            logger.exception('%s : %s' % (action, str(self)))
            failure = exception.ResourceFailure(ex, self, action)
            self.state_set(action, self.FAILED, str(failure))
            raise failure
        except:
            with excutils.save_and_reraise_exception():
                try:
                    self.state_set(action, self.FAILED,
                                   '%s aborted' % action)
                except Exception:
                    logger.exception('Error marking resource as failed')
        else:
            self.state_set(action, self.COMPLETE)

    def create(self):
        '''
        Create the resource. Subclasses should provide a handle_create() method
        to customise creation.
        '''
        action = self.CREATE
        if (self.action, self.status) != (self.INIT, self.COMPLETE):
            exc = exception.Error('State %s invalid for create'
                                  % str(self.state))
            raise exception.ResourceFailure(exc, self, action)

        logger.info('creating %s' % str(self))

        # Re-resolve the template, since if the resource Ref's
        # the AWS::StackId pseudo parameter, it will change after
        # the parser.Stack is stored (which is after the resources
        # are __init__'d, but before they are create()'d)
        self.t = self.stack.resolve_static_data(self.json_snippet)
        self.properties = Properties(self.properties_schema,
                                     self.t.get('Properties', {}),
                                     self._resolve_runtime_data,
                                     self.name)
        return self._do_action(action, self.properties.validate)

    def update(self, after, before=None):
        '''
        update the resource. Subclasses should provide a handle_update() method
        to customise update, the base-class handle_update will fail by default.
        '''
        action = self.UPDATE

        if before is None:
            before = self.parsed_template()

        if (self.action, self.status) in ((self.CREATE, self.IN_PROGRESS),
                                          (self.UPDATE, self.IN_PROGRESS)):
            exc = Exception('Resource update already requested')
            raise exception.ResourceFailure(exc, self, action)

        logger.info('updating %s' % str(self))

        try:
            self.state_set(action, self.IN_PROGRESS)
            properties = Properties(self.properties_schema,
                                    after.get('Properties', {}),
                                    self._resolve_runtime_data,
                                    self.name)
            properties.validate()
            tmpl_diff = self.update_template_diff(after, before)
            prop_diff = self.update_template_diff_properties(after, before)
            if callable(getattr(self, 'handle_update', None)):
                handle_data = self.handle_update(after, tmpl_diff, prop_diff)
                yield
                if callable(getattr(self, 'check_update_complete', None)):
                    while not self.check_update_complete(handle_data):
                        yield
        except UpdateReplace:
            logger.debug("Resource %s update requires replacement" % self.name)
            raise
        except Exception as ex:
            logger.exception('update %s : %s' % (str(self), str(ex)))
            failure = exception.ResourceFailure(ex, self, action)
            self.state_set(action, self.FAILED, str(failure))
            raise failure
        else:
            self.t = self.stack.resolve_static_data(after)
            self.state_set(action, self.COMPLETE)

    def suspend(self):
        '''
        Suspend the resource.  Subclasses should provide a handle_suspend()
        method to implement suspend
        '''
        action = self.SUSPEND

        # Don't try to suspend the resource unless it's in a stable state
        if (self.action == self.DELETE or self.status != self.COMPLETE):
            exc = exception.Error('State %s invalid for suspend'
                                  % str(self.state))
            raise exception.ResourceFailure(exc, self, action)

        logger.info('suspending %s' % str(self))
        return self._do_action(action)

    def resume(self):
        '''
        Resume the resource.  Subclasses should provide a handle_resume()
        method to implement resume
        '''
        action = self.RESUME

        # Can't resume a resource unless it's SUSPEND_COMPLETE
        if self.state != (self.SUSPEND, self.COMPLETE):
            exc = exception.Error('State %s invalid for resume'
                                  % str(self.state))
            raise exception.ResourceFailure(exc, self, action)

        logger.info('resuming %s' % str(self))
        return self._do_action(action)

    def physical_resource_name(self):
        if self.id is None:
            return None

        name = '%s-%s-%s' % (self.stack.name,
                             self.name,
                             short_id.get_id(self.id))

        if self.physical_resource_name_limit:
            name = self.reduce_physical_resource_name(
                name, self.physical_resource_name_limit)
        return name

    @staticmethod
    def reduce_physical_resource_name(name, limit):
        '''
        Reduce length of physical resource name to a limit.

        The reduced name will consist of the following:
        * the first 2 characters of the name
        * a hyphen
        * the end of the name, truncated on the left to bring
          the name length within the limit
        :param name: The name to reduce the length of
        :param limit:
        :returns: A name whose length is less than or equal to the limit
        '''
        if len(name) <= limit:
            return name

        if limit < 4:
            raise ValueError(_('limit cannot be less than 4'))

        postfix_length = limit - 3
        return name[0:2] + '-' + name[-postfix_length:]

    def validate(self):
        logger.info('Validating %s' % str(self))

        self.validate_deletion_policy(self.t)
        return self.properties.validate()

    @classmethod
    def validate_deletion_policy(cls, template):
        deletion_policy = template.get('DeletionPolicy', 'Delete')
        if deletion_policy not in ('Delete', 'Retain', 'Snapshot'):
            msg = 'Invalid DeletionPolicy %s' % deletion_policy
            raise exception.StackValidationFailed(message=msg)
        elif deletion_policy == 'Snapshot':
            if not callable(getattr(cls, 'handle_snapshot_delete', None)):
                msg = 'Snapshot DeletionPolicy not supported'
                raise exception.StackValidationFailed(message=msg)

    def delete(self):
        '''
        Delete the resource. Subclasses should provide a handle_delete() method
        to customise deletion.
        '''
        action = self.DELETE

        if (self.action, self.status) == (self.DELETE, self.COMPLETE):
            return
        # No need to delete if the resource has never been created
        if self.action == self.INIT:
            return

        initial_state = self.state

        logger.info('deleting %s' % str(self))

        try:
            self.state_set(action, self.IN_PROGRESS)

            deletion_policy = self.t.get('DeletionPolicy', 'Delete')
            handle_data = None
            if deletion_policy == 'Delete':
                if callable(getattr(self, 'handle_delete', None)):
                    handle_data = self.handle_delete()
                    yield
            elif deletion_policy == 'Snapshot':
                if callable(getattr(self, 'handle_snapshot_delete', None)):
                    handle_data = self.handle_snapshot_delete(initial_state)
                    yield

            if (deletion_policy != 'Retain' and
                    callable(getattr(self, 'check_delete_complete', None))):
                while not self.check_delete_complete(handle_data):
                    yield

        except Exception as ex:
            logger.exception('Delete %s', str(self))
            failure = exception.ResourceFailure(ex, self, self.action)
            self.state_set(action, self.FAILED, str(failure))
            raise failure
        except:
            with excutils.save_and_reraise_exception():
                try:
                    self.state_set(action, self.FAILED,
                                   'Deletion aborted')
                except Exception:
                    logger.exception('Error marking resource deletion failed')
        else:
            self.state_set(action, self.COMPLETE)

    @scheduler.wrappertask
    def destroy(self):
        '''
        Delete the resource and remove it from the database.
        '''
        yield self.delete()

        if self.id is None:
            return

        try:
            db_api.resource_get(self.context, self.id).delete()
        except exception.NotFound:
            # Don't fail on delete if the db entry has
            # not been created yet.
            pass

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
        '''Create the resource in the database.'''
        metadata = self.metadata
        try:
            rs = {'action': self.action,
                  'status': self.status,
                  'status_reason': self.status_reason,
                  'stack_id': self.stack.id,
                  'nova_instance': self.resource_id,
                  'name': self.name,
                  'rsrc_metadata': metadata,
                  'stack_name': self.stack.name}

            new_rs = db_api.resource_create(self.context, rs)
            self.id = new_rs.id

            self.stack.updated_time = datetime.utcnow()

        except Exception as ex:
            logger.error('DB error %s' % str(ex))

    def _add_event(self, action, status, reason):
        '''Add a state change event to the database.'''
        ev = event.Event(self.context, self.stack, action, status, reason,
                         self.resource_id, self.properties,
                         self.name, self.type())

        try:
            ev.store()
        except Exception as ex:
            logger.error('DB error %s' % str(ex))

    def _store_or_update(self, action, status, reason):
        self.action = action
        self.status = status
        self.status_reason = reason

        if self.id is not None:
            try:
                rs = db_api.resource_get(self.context, self.id)
                rs.update_and_save({'action': self.action,
                                    'status': self.status,
                                    'status_reason': reason,
                                    'stack_id': self.stack.id,
                                    'nova_instance': self.resource_id})

                self.stack.updated_time = datetime.utcnow()
            except Exception as ex:
                logger.error('DB error %s' % str(ex))

        # store resource in DB on transition to CREATE_IN_PROGRESS
        # all other transistions (other than to DELETE_COMPLETE)
        # should be handled by the update_and_save above..
        elif (action, status) == (self.CREATE, self.IN_PROGRESS):
            self._store()

    def _resolve_attribute(self, name):
        """
        Default implementation; should be overridden by resources that expose
        attributes

        :param name: The attribute to resolve
        :returns: the resource attribute named key
        """
        # By default, no attributes resolve
        pass

    def state_reset(self):
        """
        Reset state to (INIT, COMPLETE)
        """
        self.action = self.INIT
        self.status = self.COMPLETE

    def state_set(self, action, status, reason="state changed"):
        if action not in self.ACTIONS:
            raise ValueError("Invalid action %s" % action)

        if status not in self.STATUSES:
            raise ValueError("Invalid status %s" % status)

        old_state = (self.action, self.status)
        new_state = (action, status)
        self._store_or_update(action, status, reason)

        if new_state != old_state:
            self._add_event(action, status, reason)

    @property
    def state(self):
        '''Returns state, tuple of action, status.'''
        return (self.action, self.status)

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
        try:
            return self.attributes[key]
        except KeyError:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

    def FnBase64(self, data):
        '''
        http://docs.amazonwebservices.com/AWSCloudFormation/latest/UserGuide/\
            intrinsic-function-reference-base64.html
        '''
        return base64.b64encode(data)

    def signal(self, details=None):
        '''
        signal the resource. Subclasses should provide a handle_signal() method
        to implement the signal, the base-class raise an exception if no
        handler is implemented.
        '''
        def get_string_details():
            if details is None:
                return 'No signal details provided'
            if isinstance(details, basestring):
                return details
            if isinstance(details, dict):
                if all(k in details for k in ('previous', 'current',
                                              'reason')):
                    # this is from Ceilometer.
                    auto = '%(previous)s to %(current)s (%(reason)s)' % details
                    return 'alarm state changed from %s' % auto
                elif 'state' in details:
                    # this is from watchrule
                    return 'alarm state changed to %(state)s' % details

            return 'Unknown'

        try:
            if self.action in (self.SUSPEND, self.DELETE):
                msg = 'Cannot signal resource during %s' % self.action
                raise Exception(msg)

            if not callable(getattr(self, 'handle_signal', None)):
                msg = 'Resource %s is not able to receive a signal' % str(self)
                raise Exception(msg)

            self._add_event('signal', self.status, get_string_details())
            self.handle_signal(details)
        except Exception as ex:
            logger.exception('signal %s : %s' % (str(self), str(ex)))
            failure = exception.ResourceFailure(ex, self)
            raise failure

    def handle_update(self, json_snippet=None, tmpl_diff=None, prop_diff=None):
        raise UpdateReplace(self.name)

    def metadata_update(self, new_metadata=None):
        '''
        No-op for resources which don't explicitly override this method
        '''
        if new_metadata:
            logger.warning("Resource %s does not implement metadata update" %
                           self.name)

    @classmethod
    def resource_to_template(cls, resource_type):
        '''
        :param resource_type: The resource type to be displayed in the template
        :param explode_nested: True if a resource's nested properties schema
            should be resolved.
        :returns: A template where the resource's properties_schema is mapped
            as parameters, and the resource's attributes_schema is mapped as
            outputs
        '''
        (parameters, properties) = (Properties.
                                    schema_to_parameters_and_properties(
                                        cls.properties_schema))

        resource_name = cls.__name__
        return {
            'Parameters': parameters,
            'Resources': {
                resource_name: {
                    'Type': resource_type,
                    'Properties': properties
                }
            },
            'Outputs': Attributes.as_outputs(resource_name, cls)
        }
