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
import six
from six import reraise as raise_

from heat.common.i18n import _
from heat.common.i18n import _LE

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

    def __init__(self, **kwargs):
        self.kwargs = kwargs

        try:
            if self.error_code in ERROR_CODE_MAP:
                self.msg_fmt = ERROR_CODE_MAP[self.error_code]

            self.message = self.msg_fmt % kwargs

            if self.error_code:
                self.message = 'HEAT-E%s %s' % (self.error_code, self.message)
        except KeyError:
            exc_info = sys.exc_info()
            # kwargs doesn't match a variable in the message
            # log the issue and the kwargs
            LOG.exception(_LE('Exception in string format operation'))
            for name, value in six.iteritems(kwargs):
                LOG.error(_LE("%(name)s: %(value)s"),
                          {'name': name, 'value': value})  # noqa

            if _FATAL_EXCEPTION_FORMAT_ERRORS:
                raise_(exc_info[0], exc_info[1], exc_info[2])

    def __str__(self):
        return self.message

    def __deepcopy__(self, memo):
        return self.__class__(**self.kwargs)


class MissingCredentialError(HeatException):
    msg_fmt = _("Missing required credential: %(required)s")


class AuthorizationFailure(HeatException):
    msg_fmt = _("Authorization failed.")


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


class InvalidTemplateParameter(HeatException):
    msg_fmt = _("The Parameter (%(key)s) has no attributes.")


class InvalidTemplateAttribute(HeatException):
    msg_fmt = _("The Referenced Attribute (%(resource)s %(key)s)"
                " is incorrect.")


class InvalidTemplateReference(HeatException):
    msg_fmt = _('The specified reference "%(resource)s" (in %(key)s)'
                ' is incorrect.')


class EntityNotFound(HeatException):
    msg_fmt = _("The %(entity)s (%(name)s) could not be found.")

    def __init__(self, entity=None, name=None, **kwargs):
        self.entity = entity
        self.name = name
        super(EntityNotFound, self).__init__(entity=entity, name=name,
                                             **kwargs)


class PhysicalResourceNameAmbiguity(HeatException):
    msg_fmt = _(
        "Multiple physical resources were found with name (%(name)s).")


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

    def error(self):
        return self.error

    def path(self):
        return self.path

    def error_message(self):
        return self.error_message


class StackValidationFailed(HeatExceptionWithPath):
    pass


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


class ResourceNotAvailable(HeatException):
    msg_fmt = _("The Resource (%(resource_name)s) is not available.")


class WatchRuleNotFound(EntityNotFound):
    """Keep this for AWS compatiblility."""
    msg_fmt = _("The Watch Rule (%(watch_name)s) could not be found.")


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
                'must be specified: %(props)s')

    def __init__(self, *args, **kwargs):
        if args:
            kwargs.update({'props': ", ".join(args)})
        super(PropertyUnspecifiedError, self).__init__(**kwargs)


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


class StackResourceLimitExceeded(HeatException):
    msg_fmt = _('Maximum resources per stack exceeded.')


class ActionInProgress(HeatException):
    msg_fmt = _("Stack %(stack_name)s already has an action (%(action)s) "
                "in progress.")


class StopActionFailed(HeatException):
    msg_fmt = _("Failed to stop stack (%(stack_name)s) on other engine "
                "(%(engine_id)s)")


class EventSendFailed(HeatException):
    msg_fmt = _("Failed to send message to stack (%(stack_name)s) "
                "on other engine (%(engine_id)s)")


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


class DeploymentConcurrentTransaction(HeatException):
    msg_fmt = _('Concurrent transaction for deployments of server %(server)s')


class ObjectFieldInvalid(HeatException):
    msg_fmt = _('Field %(field)s of %(objname)s is not an instance of Field')


class KeystoneServiceNameConflict(HeatException):
    msg_fmt = _("Keystone has more than one service with same name "
                "%(service)s. Please use service id instead of name")


class SIGHUPInterrupt(HeatException):
    msg_fmt = _("System SIGHUP signal received.")


class NoActionRequired(Exception):
    pass
