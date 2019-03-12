#
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Heat exception subclasses"""

import sys

from oslo_log import log as logging
from oslo_utils import excutils

import six

from heat.common.i18n import _

_FATAL_EXCEPTION_FORMAT_ERRORS = False


LOG = logging.getLogger(__name__)


# TODO(kanagaraj-manickam): Expose this to user via REST API
ERROR_CODE_MAP = {
    '99001': _("Service %(service_name)s is not available for resource "
               "type %(resource_type)s, reason: %(reason)s")
}


@six.python_2_unicode_compatible
class HeatException(Exception):
    """Base Heat Exception.

    To correctly use this class, inherit from it and define a 'msg_fmt'
    property. That msg_fmt will get formatted with the keyword arguments
    provided to the constructor.
    """
    message = _("An unknown exception occurred.")
    # error_code helps to provide an unique number for a given exception
    # and is encoded in XXYYY format.
    # Here, XX - For each of the entity type like stack, resource, etc
    # an unique number will be provided. All exceptions for a entity will
    # have same XX code.
    # YYY - Specific error code for a given exception.
    error_code = None

    safe = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs

        if self.error_code in ERROR_CODE_MAP:
            self.msg_fmt = ERROR_CODE_MAP[self.error_code]

        try:
            self.message = self.msg_fmt % kwargs
        except KeyError:
            with excutils.save_and_reraise_exception(
                    reraise=_FATAL_EXCEPTION_FORMAT_ERRORS):
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception('Exception in string format operation')
                for name, value in six.iteritems(kwargs):
                    LOG.error("%(name)s: %(value)s",
                              {'name': name, 'value': value})  # noqa

        if self.error_code:
            self.message = 'HEAT-E%s %s' % (self.error_code, self.message)

    def __str__(self):
        return self.message

    def __deepcopy__(self, memo):
        return self.__class__(**self.kwargs)


class MissingCredentialError(HeatException):
    msg_fmt = _("Missing required credential: %(required)s")


class AuthorizationFailure(HeatException):
    msg_fmt = _("Authorization failed.%(failure_reason)s")

    def __init__(self, failure_reason=""):
        if failure_reason != "":
            # Add a space to make message more readable
            failure_reason = " " + failure_reason
        super(AuthorizationFailure, self).__init__(
            failure_reason=failure_reason)


class NotAuthenticated(HeatException):
    msg_fmt = _("You are not authenticated.")


class Forbidden(HeatException):
    msg_fmt = _("You are not authorized to use %(action)s.")

    def __init__(self, action='this action'):
        super(Forbidden, self).__init__(action=action)


# NOTE(bcwaldon): here for backwards-compatibility, need to deprecate.
class NotAuthorized(Forbidden):
    msg_fmt = _("You are not authorized to complete this action.")


class Invalid(HeatException):
    msg_fmt = _("Data supplied was not valid: %(reason)s")


class UserParameterMissing(HeatException):
    msg_fmt = _("The Parameter (%(key)s) was not provided.")


class UnknownUserParameter(HeatException):
    msg_fmt = _("The Parameter (%(key)s) was not defined in template.")


class InvalidTemplateVersion(HeatException):
    msg_fmt = _("The template version is invalid: %(explanation)s")


class InvalidTemplateSection(HeatException):
    msg_fmt = _("The template section is invalid: %(section)s")


class ImmutableParameterModified(HeatException):
    msg_fmt = _("The following parameters are immutable and may not be "
                "updated: %(keys)s")

    def __init__(self, *args, **kwargs):
        if args:
            kwargs.update({'keys': ", ".join(args)})
        super(ImmutableParameterModified, self).__init__(**kwargs)


class InvalidMergeStrategyForParam(HeatException):
    msg_fmt = _("Invalid merge strategy '%(strategy)s' for "
                "parameter '%(param)s'.")


class ConflictingMergeStrategyForParam(HeatException):
    msg_fmt = _("Conflicting merge strategy '%(strategy)s' for "
                "parameter '%(param)s' in file '%(env_file)s'.")


class InvalidTemplateAttribute(HeatException):
    msg_fmt = _("The Referenced Attribute (%(resource)s %(key)s)"
                " is incorrect.")


class InvalidTemplateReference(HeatException):
    msg_fmt = _('The specified reference "%(resource)s" (in %(key)s)'
                ' is incorrect.')


class TemplateOutputError(HeatException):
    msg_fmt = _('Error in %(resource)s output %(attribute)s: %(message)s')


class InvalidEncryptionKey(HeatException):
    msg_fmt = _('Can not decrypt data with the auth_encryption_key'
                ' in heat config.')


class InvalidExternalResourceDependency(HeatException):
    msg_fmt = _("Invalid dependency with external %(resource_type)s "
                "resource: %(external_id)s")


class EntityNotFound(HeatException):
    msg_fmt = _("The %(entity)s (%(name)s) could not be found.")

    def __init__(self, entity=None, name=None, **kwargs):
        self.entity = entity
        self.name = name
        super(EntityNotFound, self).__init__(entity=entity, name=name,
                                             **kwargs)


class PhysicalResourceExists(HeatException):
    msg_fmt = _("The physical resource for (%(name)s) exists.")


class PhysicalResourceNameAmbiguity(HeatException):
    msg_fmt = _(
        "Multiple physical resources were found with name (%(name)s).")


class PhysicalResourceIDAmbiguity(HeatException):
    msg_fmt = _(
        "Multiple resources were found with the physical ID (%(phys_id)s).")


class InvalidTenant(HeatException):
    msg_fmt = _("Searching Tenant %(target)s "
                "from Tenant %(actual)s forbidden.")


class StackExists(HeatException):
    msg_fmt = _("The Stack (%(stack_name)s) already exists.")


class HeatExceptionWithPath(HeatException):
    msg_fmt = _("%(error)s%(path)s%(message)s")

    def __init__(self, error=None, path=None, message=None):
        self.error = error or ''
        self.path = []
        if path is not None:
            if isinstance(path, list):
                self.path = path
            elif isinstance(path, six.string_types):
                self.path = [path]

        result_path = ''
        for path_item in self.path:
            if isinstance(path_item, int) or path_item.isdigit():
                result_path += '[%s]' % path_item
            elif len(result_path) > 0:
                result_path += '.%s' % path_item
            else:
                result_path = path_item

        self.error_message = message or ''
        super(HeatExceptionWithPath, self).__init__(
            error=('%s: ' % self.error if self.error != '' else ''),
            path=('%s: ' % result_path if len(result_path) > 0 else ''),
            message=self.error_message
        )


class StackValidationFailed(HeatExceptionWithPath):
    def __init__(self, error=None, path=None, message=None,
                 resource=None):
        if path is None:
            path = []
        elif isinstance(path, six.string_types):
            path = [path]

        if resource is not None and not path:
            path = [resource.stack.t.get_section_name(
                resource.stack.t.RESOURCES), resource.name]
        if isinstance(error, Exception):
            if isinstance(error, StackValidationFailed):
                str_error = error.error
                message = error.error_message
                path = path + error.path
                # This is a hack to avoid the py3 (chained exception)
                # json serialization circular reference error from
                # oslo.messaging.
                self.args = error.args
            else:
                str_error = six.text_type(type(error).__name__)
                message = six.text_type(error)
        else:
            str_error = error

        super(StackValidationFailed, self).__init__(error=str_error, path=path,
                                                    message=message)


class InvalidSchemaError(HeatException):
    msg_fmt = _("%(message)s")


class ResourceNotFound(EntityNotFound):
    msg_fmt = _("The Resource (%(resource_name)s) could not be found "
                "in Stack %(stack_name)s.")


class SnapshotNotFound(EntityNotFound):
    msg_fmt = _("The Snapshot (%(snapshot)s) for Stack (%(stack)s) "
                "could not be found.")


class InvalidGlobalResource(HeatException):
    msg_fmt = _("There was an error loading the definition of the global "
                "resource type %(type_name)s.")


class ResourceTypeUnavailable(HeatException):
    error_code = '99001'


class InvalidBreakPointHook(HeatException):
    msg_fmt = _("%(message)s")


class InvalidRestrictedAction(HeatException):
    msg_fmt = _("%(message)s")


class ResourceNotAvailable(HeatException):
    msg_fmt = _("The Resource (%(resource_name)s) is not available.")


class ClientNotAvailable(HeatException):
    msg_fmt = _("The client (%(client_name)s) is not available.")


class ResourceFailure(HeatExceptionWithPath):
    def __init__(self, exception_or_error, resource, action=None):
        self.resource = resource
        self.action = action
        if action is None and resource is not None:
            self.action = resource.action
        path = []
        res_path = []
        if resource is not None:
            res_path = [resource.stack.t.get_section_name('resources'),
                        resource.name]

        if isinstance(exception_or_error, Exception):
            if isinstance(exception_or_error, ResourceFailure):
                self.exc = exception_or_error.exc
                error = exception_or_error.error
                message = exception_or_error.error_message
                path = exception_or_error.path
            else:
                self.exc = exception_or_error
                error = six.text_type(type(self.exc).__name__)
                message = six.text_type(self.exc)
                path = res_path
        else:
            self.exc = None
            res_failed = 'Resource %s failed: ' % action.upper()
            if res_failed in exception_or_error:
                (error, message, new_path) = self._from_status_reason(
                    exception_or_error)
                path = res_path + new_path
            else:
                path = res_path
                error = None
                message = exception_or_error

        super(ResourceFailure, self).__init__(error=error, path=path,
                                              message=message)

    def _from_status_reason(self, status_reason):
        """Split the status_reason up into parts.

        Given the following status_reason:
        "Resource DELETE failed: Exception : resources.AResource: foo"

        we are going to return:
        ("Exception", "resources.AResource", "foo")
        """
        parsed = [sp.strip() for sp in status_reason.split(':')]
        if len(parsed) >= 4:
            error = parsed[1]
            message = ': '.join(parsed[3:])
            path = parsed[2].split('.')
        else:
            error = ''
            message = status_reason
            path = []
        return (error, message, path)


class NotSupported(HeatException):
    msg_fmt = _("%(feature)s is not supported.")


class ResourceActionNotSupported(HeatException):
    msg_fmt = _("%(action)s is not supported for resource.")


class ResourceActionRestricted(HeatException):
    msg_fmt = _("%(action)s is restricted for resource.")


class ResourcePropertyConflict(HeatException):
    msg_fmt = _('Cannot define the following properties '
                'at the same time: %(props)s.')

    def __init__(self, *args, **kwargs):
        if args:
            kwargs.update({'props': ", ".join(args)})
        super(ResourcePropertyConflict, self).__init__(**kwargs)


class ResourcePropertyDependency(HeatException):
    msg_fmt = _('%(prop1)s cannot be specified without %(prop2)s.')


class ResourcePropertyValueDependency(HeatException):
    msg_fmt = _('%(prop1)s property should only be specified '
                'for %(prop2)s with value %(value)s.')


class PropertyUnspecifiedError(HeatException):
    msg_fmt = _('At least one of the following properties '
                'must be specified: %(props)s.')

    def __init__(self, *args, **kwargs):
        if args:
            kwargs.update({'props': ", ".join(args)})
        super(PropertyUnspecifiedError, self).__init__(**kwargs)


# Do not reference this here - in the future it will move back to its
# correct (and original) location in heat.engine.resource. Reference it as
# heat.engine.resource.UpdateReplace instead.
class UpdateReplace(Exception):
    """Raised when resource update requires replacement."""
    def __init__(self, resource_name='Unknown'):
        msg = _("The Resource %s requires replacement.") % resource_name
        super(Exception, self).__init__(six.text_type(msg))


class ResourceUnknownStatus(HeatException):
    msg_fmt = _('%(result)s - Unknown status %(resource_status)s due to '
                '"%(status_reason)s"')

    def __init__(self, result=_('Resource failed'),
                 status_reason=_('Unknown'), **kwargs):
        super(ResourceUnknownStatus, self).__init__(
            result=result, status_reason=status_reason, **kwargs)


class ResourceInError(HeatException):
    msg_fmt = _('Went to status %(resource_status)s '
                'due to "%(status_reason)s"')

    def __init__(self, status_reason=_('Unknown'), **kwargs):
        super(ResourceInError, self).__init__(status_reason=status_reason,
                                              **kwargs)


class UpdateInProgress(Exception):
    def __init__(self, resource_name='Unknown'):
        msg = _("The resource %s is already being updated.") % resource_name
        super(Exception, self).__init__(six.text_type(msg))


class HTTPExceptionDisguise(Exception):
    """Disguises HTTP exceptions.

    They can be handled by the webob fault application in the wsgi pipeline.
    """

    safe = True

    def __init__(self, exception):
        self.exc = exception
        self.tb = sys.exc_info()[2]


class EgressRuleNotAllowed(HeatException):
    msg_fmt = _("Egress rules are only allowed when "
                "Neutron is used and the 'VpcId' property is set.")


class Error(HeatException):
    msg_fmt = "%(message)s"

    def __init__(self, msg):
        super(Error, self).__init__(message=msg)


class NotFound(HeatException):
    def __init__(self, msg_fmt=_('Not found')):
        self.msg_fmt = msg_fmt
        super(NotFound, self).__init__()


class InvalidContentType(HeatException):
    msg_fmt = _("Invalid content type %(content_type)s")


class RequestLimitExceeded(HeatException):
    msg_fmt = _('Request limit exceeded: %(message)s')


class DownloadLimitExceeded(HeatException):
    msg_fmt = _('Permissible download limit exceeded: %(message)s')


class StackResourceLimitExceeded(HeatException):
    msg_fmt = _('Maximum resources per stack exceeded.')


class ActionInProgress(HeatException):
    msg_fmt = _("Stack %(stack_name)s already has an action (%(action)s) "
                "in progress.")


class ActionNotComplete(HeatException):
    msg_fmt = _("Stack %(stack_name)s has an action (%(action)s) "
                "in progress or failed state.")


class StopActionFailed(HeatException):
    msg_fmt = _("Failed to stop stack (%(stack_name)s) on other engine "
                "(%(engine_id)s)")


class EventSendFailed(HeatException):
    msg_fmt = _("Failed to send message to stack (%(stack_name)s) "
                "on other engine (%(engine_id)s)")


class InterfaceAttachFailed(HeatException):
    msg_fmt = _("Failed to attach interface (%(port)s) "
                "to server (%(server)s)")


class InterfaceDetachFailed(HeatException):
    msg_fmt = _("Failed to detach interface (%(port)s) "
                "from server (%(server)s)")


class UnsupportedObjectError(HeatException):
    msg_fmt = _('Unsupported object type %(objtype)s')


class OrphanedObjectError(HeatException):
    msg_fmt = _('Cannot call %(method)s on orphaned %(objtype)s object')


class IncompatibleObjectVersion(HeatException):
    msg_fmt = _('Version %(objver)s of %(objname)s is not supported')


class ObjectActionError(HeatException):
    msg_fmt = _('Object action %(action)s failed because: %(reason)s')


class ReadOnlyFieldError(HeatException):
    msg_fmt = _('Cannot modify readonly field %(field)s')


class ConcurrentTransaction(HeatException):
    msg_fmt = _('Concurrent transaction for %(action)s')


class ObjectFieldInvalid(HeatException):
    msg_fmt = _('Field %(field)s of %(objname)s is not an instance of Field')


class KeystoneServiceNameConflict(HeatException):
    msg_fmt = _("Keystone has more than one service with same name "
                "%(service)s. Please use service id instead of name")


class SIGHUPInterrupt(HeatException):
    msg_fmt = _("System SIGHUP signal received.")


class InvalidServiceVersion(HeatException):
    msg_fmt = _("Invalid service %(service)s version %(version)s")


class InvalidTemplateVersions(HeatException):
    msg_fmt = _('A template version alias %(version)s was added for a '
                'template class that has no official YYYY-MM-DD version.')


class UnableToAutoAllocateNetwork(HeatException):
    msg_fmt = _('Unable to automatically allocate a network: %(message)s')
