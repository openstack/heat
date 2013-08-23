# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
import urlparse
import sys
from heat.openstack.common import exception


OpenstackException = exception.OpenstackException
NotFound = exception.NotFound
Error = exception.Error
InvalidContentType = exception.InvalidContentType


class RedirectException(Exception):
    def __init__(self, url):
        self.url = urlparse.urlparse(url)


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


class MissingCredentialError(OpenstackException):
    message = _("Missing required credential: %(required)s")


class BadAuthStrategy(OpenstackException):
    message = _("Incorrect auth strategy, expected \"%(expected)s\" but "
                "received \"%(received)s\"")


class AuthBadRequest(OpenstackException):
    message = _("Connect error/bad request to Auth service at URL %(url)s.")


class AuthUrlNotFound(OpenstackException):
    message = _("Auth service at URL %(url)s not found.")


class AuthorizationFailure(OpenstackException):
    message = _("Authorization failed.")


class NotAuthenticated(OpenstackException):
    message = _("You are not authenticated.")


class Forbidden(OpenstackException):
    message = _("You are not authorized to complete this action.")


#NOTE(bcwaldon): here for backwards-compatability, need to deprecate.
class NotAuthorized(Forbidden):
    message = _("You are not authorized to complete this action.")


class Invalid(OpenstackException):
    message = _("Data supplied was not valid: %(reason)s")


class AuthorizationRedirect(OpenstackException):
    message = _("Redirecting to %(uri)s for authorization.")


class ClientConfigurationError(OpenstackException):
    message = _("There was an error configuring the client.")


class MultipleChoices(OpenstackException):
    message = _("The request returned a 302 Multiple Choices. This generally "
                "means that you have not included a version indicator in a "
                "request URI.\n\nThe body of response returned:\n%(body)s")


class LimitExceeded(OpenstackException):
    message = _("The request returned a 413 Request Entity Too Large. This "
                "generally means that rate limiting or a quota threshold was "
                "breached.\n\nThe response body:\n%(body)s")

    def __init__(self, *args, **kwargs):
        self.retry_after = (int(kwargs['retry']) if kwargs.get('retry')
                            else None)
        super(LimitExceeded, self).__init__(*args, **kwargs)


class ServiceUnavailable(OpenstackException):
    message = _("The request returned a 503 ServiceUnavilable. This "
                "generally occurs on service overload or other transient "
                "outage.")

    def __init__(self, *args, **kwargs):
        self.retry_after = (int(kwargs['retry']) if kwargs.get('retry')
                            else None)
        super(ServiceUnavailable, self).__init__(*args, **kwargs)


class RequestUriTooLong(OpenstackException):
    message = _("The URI was too long.")


class ServerError(OpenstackException):
    message = _("The request returned 500 Internal Server Error"
                "\n\nThe response body:\n%(body)s")


class MaxRedirectsExceeded(OpenstackException):
    message = _("Maximum redirects (%(redirects)s) was exceeded.")


class InvalidRedirect(OpenstackException):
    message = _("Received invalid HTTP redirect.")


class NoServiceEndpoint(OpenstackException):
    message = _("Response from Keystone does not contain a Heat endpoint.")


class RegionAmbiguity(OpenstackException):
    message = _("Multiple 'image' service matches for region %(region)s. This "
                "generally means that a region is required and you have not "
                "supplied one.")


class UserParameterMissing(OpenstackException):
    message = _("The Parameter (%(key)s) was not provided.")


class UnknownUserParameter(OpenstackException):
    message = _("The Parameter (%(key)s) was not defined in template.")


class InvalidTemplateAttribute(OpenstackException):
    message = _("The Referenced Attribute (%(resource)s %(key)s)"
                " is incorrect.")


class InvalidTemplateReference(OpenstackException):
    message = _("The specified reference (%(resource)s %(key)s)"
                " is incorrect.")


class UserKeyPairMissing(OpenstackException):
    message = _("The Key (%(key_name)s) could not be found.")


class FlavorMissing(OpenstackException):
    message = _("The Flavor ID (%(flavor_id)s) could not be found.")


class ImageNotFound(OpenstackException):
    message = _("The Image (%(image_name)s) could not be found.")


class NoUniqueImageFound(OpenstackException):
    message = _("Multiple images were found with name (%(image_name)s).")


class InvalidTenant(OpenstackException):
    message = _("Searching Tenant %(target)s "
                "from Tenant %(actual)s forbidden.")


class StackNotFound(OpenstackException):
    message = _("The Stack (%(stack_name)s) could not be found.")


class StackExists(OpenstackException):
    message = _("The Stack (%(stack_name)s) already exists.")


class StackValidationFailed(OpenstackException):
    message = _("%(message)s")


class ResourceNotFound(OpenstackException):
    message = _("The Resource (%(resource_name)s) could not be found "
                "in Stack %(stack_name)s.")


class ResourceTypeNotFound(OpenstackException):
    message = _("The Resource Type (%(type_name)s) could not be found.")


class ResourceNotAvailable(OpenstackException):
    message = _("The Resource (%(resource_name)s) is not available.")


class PhysicalResourceNotFound(OpenstackException):
    message = _("The Resource (%(resource_id)s) could not be found.")


class WatchRuleNotFound(OpenstackException):
    message = _("The Watch Rule (%(watch_name)s) could not be found.")


class ResourceFailure(OpenstackException):
    message = _("%(exc_type)s: %(message)s")

    def __init__(self, exception, resource, action=None):
        if isinstance(exception, ResourceFailure):
            exception = getattr(exception, 'exc', exception)
        self.exc = exception
        self.resource = resource
        self.action = action
        exc_type = type(exception).__name__
        super(ResourceFailure, self).__init__(exc_type=exc_type,
                                              message=str(exception))


class NotSupported(OpenstackException):
    message = _("%(feature)s is not supported.")


class ResourcePropertyConflict(OpenstackException):
    message = _('Cannot define the following properties at the same time: %s.')

    def __init__(self, *args):
        self.message = self.message % ", ".join(args)
        super(ResourcePropertyConflict, self).__init__()


class HTTPExceptionDisguise(Exception):
    """Disguises HTTP exceptions so they can be handled by the webob fault
    application in the wsgi pipeline.
    """

    def __init__(self, exception):
        self.exc = exception
        self.tb = sys.exc_info()[2]


class TemplateTooBig(OpenstackException):
    message = _('Template exceeds maximum allowed size.')
