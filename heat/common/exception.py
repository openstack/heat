
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

import functools
import sys

from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging
from heat.openstack.common.py3kcompat import urlutils


_FATAL_EXCEPTION_FORMAT_ERRORS = False


logger = logging.getLogger(__name__)


class RedirectException(Exception):
    def __init__(self, url):
        self.url = urlutils.urlparse(url)


class KeystoneError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __str__(self):
        return "Code: %s, message: %s" % (self.code, self.message)


def wrap_exception(notifier=None, publisher_id=None, event_type=None,
                   level=None):
    """This decorator wraps a method to catch any exceptions that may
    get thrown. It logs the exception as well as optionally sending
    it to the notification system.
    """
    # TODO(sandy): Find a way to import nova.notifier.api so we don't have
    # to pass it in as a parameter. Otherwise we get a cyclic import of
    # nova.notifier.api -> nova.utils -> nova.exception :(
    # TODO(johannes): Also, it would be nice to use
    # utils.save_and_reraise_exception() without an import loop
    def inner(f):
        def wrapped(*args, **kw):
            try:
                return f(*args, **kw)
            except Exception as e:
                # Save exception since it can be clobbered during processing
                # below before we can re-raise
                exc_info = sys.exc_info()

                if notifier:
                    payload = dict(args=args, exception=e)
                    payload.update(kw)

                    # Use a temp vars so we don't shadow
                    # our outer definitions.
                    temp_level = level
                    if not temp_level:
                        temp_level = notifier.ERROR

                    temp_type = event_type
                    if not temp_type:
                        # If f has multiple decorators, they must use
                        # functools.wraps to ensure the name is
                        # propagated.
                        temp_type = f.__name__

                    notifier.notify(publisher_id, temp_type, temp_level,
                                    payload)

                # re-raise original exception since it may have been clobbered
                raise exc_info[0], exc_info[1], exc_info[2]

        return functools.wraps(f)(wrapped)
    return inner


class HeatException(Exception):
    """Base Heat Exception

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property. That msg_fmt will get printf'd
    with the keyword arguments provided to the constructor.

    """
    message = _("An unknown exception occurred.")

    def __init__(self, **kwargs):
        self.kwargs = kwargs

        try:
            self.message = self.msg_fmt % kwargs
        except KeyError:
            exc_info = sys.exc_info()
            #kwargs doesn't match a variable in the message
            #log the issue and the kwargs
            logger.exception(_('Exception in string format operation'))
            for name, value in kwargs.iteritems():
                logger.error("%s: %s" % (name, value))

            if _FATAL_EXCEPTION_FORMAT_ERRORS:
                raise exc_info[0], exc_info[1], exc_info[2]

    def __str__(self):
        return str(self.message)

    def __unicode__(self):
        return unicode(self.message)


class MissingCredentialError(HeatException):
    msg_fmt = _("Missing required credential: %(required)s")


class BadAuthStrategy(HeatException):
    msg_fmt = _("Incorrect auth strategy, expected \"%(expected)s\" but "
                "received \"%(received)s\"")


class AuthBadRequest(HeatException):
    msg_fmt = _("Connect error/bad request to Auth service at URL %(url)s.")


class AuthUrlNotFound(HeatException):
    msg_fmt = _("Auth service at URL %(url)s not found.")


class AuthorizationFailure(HeatException):
    msg_fmt = _("Authorization failed.")


class NotAuthenticated(HeatException):
    msg_fmt = _("You are not authenticated.")


class Forbidden(HeatException):
    msg_fmt = _("You are not authorized to complete this action.")


#NOTE(bcwaldon): here for backwards-compatability, need to deprecate.
class NotAuthorized(Forbidden):
    msg_fmt = _("You are not authorized to complete this action.")


class Invalid(HeatException):
    msg_fmt = _("Data supplied was not valid: %(reason)s")


class AuthorizationRedirect(HeatException):
    msg_fmt = _("Redirecting to %(uri)s for authorization.")


class RequestUriTooLong(HeatException):
    msg_fmt = _("The URI was too long.")


class MaxRedirectsExceeded(HeatException):
    msg_fmt = _("Maximum redirects (%(redirects)s) was exceeded.")


class InvalidRedirect(HeatException):
    msg_fmt = _("Received invalid HTTP redirect.")


class RegionAmbiguity(HeatException):
    msg_fmt = _("Multiple 'image' service matches for region %(region)s. This "
                "generally means that a region is required and you have not "
                "supplied one.")


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
    msg_fmt = _("The specified reference \"%(resource)s\" (in %(key)s)"
                " is incorrect.")


class UserKeyPairMissing(HeatException):
    msg_fmt = _("The Key (%(key_name)s) could not be found.")


class FlavorMissing(HeatException):
    msg_fmt = _("The Flavor ID (%(flavor_id)s) could not be found.")


class ImageNotFound(HeatException):
    msg_fmt = _("The Image (%(image_name)s) could not be found.")


class PhysicalResourceNameAmbiguity(HeatException):
    msg_fmt = _(
        "Multiple physical resources were found with name (%(name)s).")


class InvalidTenant(HeatException):
    msg_fmt = _("Searching Tenant %(target)s "
                "from Tenant %(actual)s forbidden.")


class StackNotFound(HeatException):
    msg_fmt = _("The Stack (%(stack_name)s) could not be found.")


class StackExists(HeatException):
    msg_fmt = _("The Stack (%(stack_name)s) already exists.")


class StackValidationFailed(HeatException):
    msg_fmt = _("%(message)s")


class ResourceNotFound(HeatException):
    msg_fmt = _("The Resource (%(resource_name)s) could not be found "
                "in Stack %(stack_name)s.")


class ResourceTypeNotFound(HeatException):
    msg_fmt = _("The Resource Type (%(type_name)s) could not be found.")


class ResourceNotAvailable(HeatException):
    msg_fmt = _("The Resource (%(resource_name)s) is not available.")


class PhysicalResourceNotFound(HeatException):
    msg_fmt = _("The Resource (%(resource_id)s) could not be found.")


class WatchRuleNotFound(HeatException):
    msg_fmt = _("The Watch Rule (%(watch_name)s) could not be found.")


class ResourceFailure(HeatException):
    msg_fmt = _("%(exc_type)s: %(message)s")

    def __init__(self, exception, resource, action=None):
        if isinstance(exception, ResourceFailure):
            exception = getattr(exception, 'exc', exception)
        self.exc = exception
        self.resource = resource
        self.action = action
        exc_type = type(exception).__name__
        super(ResourceFailure, self).__init__(exc_type=exc_type,
                                              message=str(exception))


class NotSupported(HeatException):
    msg_fmt = _("%(feature)s is not supported.")


class ResourcePropertyConflict(HeatException):
    msg_fmt = _('Cannot define the following properties at the same time: %s.')

    def __init__(self, *args):
        self.msg_fmt = self.msg_fmt % ", ".join(args)
        super(ResourcePropertyConflict, self).__init__()


class HTTPExceptionDisguise(Exception):
    """Disguises HTTP exceptions so they can be handled by the webob fault
    application in the wsgi pipeline.
    """

    def __init__(self, exception):
        self.exc = exception
        self.tb = sys.exc_info()[2]


class EgressRuleNotAllowed(HeatException):
    msg_fmt = _("Egress rules are only allowed when "
                "Neutron is used and the 'VpcId' property is set.")


class Error(HeatException):
    def __init__(self, msg_fmt):
        self.msg_fmt = msg_fmt
        super(Error, self).__init__()


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


class SoftwareConfigMissing(HeatException):
    msg_fmt = _("The config (%(software_config_id)s) could not be found.")


class StopActionFailed(HeatException):
    msg_fmt = _("Failed to stop stack (%(stack_name)s) on other engine "
                "(%(engine_id)s)")
