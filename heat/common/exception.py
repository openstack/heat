# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

import urlparse


class RedirectException(Exception):
    def __init__(self, url):
        self.url = urlparse.urlparse(url)


class HeatException(Exception):
    """
    Base Heat Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.
    """
    message = _("An unknown exception occurred")

    def __init__(self, *args, **kwargs):
        try:
            self._error_string = self.message % kwargs
        except Exception:
            # at least get the core message out if something happened
            self._error_string = self.message
        if len(args) > 0:
            # If there is a non-kwarg parameter, assume it's the error
            # message or reason description and tack it on to the end
            # of the exception message
            # Convert all arguments into their string representations...
            args = ["%s" % arg for arg in args]
            self._error_string = (self._error_string +
                                  "\nDetails: %s" % '\n'.join(args))

    def __str__(self):
        return self._error_string


class MissingArgumentError(HeatException):
    message = _("Missing required argument.")


class MissingCredentialError(HeatException):
    message = _("Missing required credential: %(required)s")


class BadAuthStrategy(HeatException):
    message = _("Incorrect auth strategy, expected \"%(expected)s\" but "
                "received \"%(received)s\"")


class NotFound(HeatException):
    message = _("An object with the specified identifier was not found.")


class UnknownScheme(HeatException):
    message = _("Unknown scheme '%(scheme)s' found in URI")


class BadStoreUri(HeatException):
    message = _("The Store URI %(uri)s was malformed. Reason: %(reason)s")


class Duplicate(HeatException):
    message = _("An object with the same identifier already exists.")


class StorageFull(HeatException):
    message = _("There is not enough disk space on the image storage media.")


class StorageWriteDenied(HeatException):
    message = _("Permission to write image storage media denied.")


class ImportFailure(HeatException):
    message = _("Failed to import requested object/class: '%(import_str)s'. "
                "Reason: %(reason)s")


class AuthBadRequest(HeatException):
    message = _("Connect error/bad request to Auth service at URL %(url)s.")


class AuthUrlNotFound(HeatException):
    message = _("Auth service at URL %(url)s not found.")


class AuthorizationFailure(HeatException):
    message = _("Authorization failed.")


class NotAuthorized(HeatException):
    message = _("You are not authorized to complete this action.")


class NotAuthorizedPublicImage(NotAuthorized):
    message = _("You are not authorized to complete this action.")


class Invalid(HeatException):
    message = _("Data supplied was not valid.")


class AuthorizationRedirect(HeatException):
    message = _("Redirecting to %(uri)s for authorization.")


class DatabaseMigrationError(HeatException):
    message = _("There was an error migrating the database.")


class ClientConnectionError(HeatException):
    message = _("There was an error connecting to a server")


class ClientConfigurationError(HeatException):
    message = _("There was an error configuring the client.")


class MultipleChoices(HeatException):
    message = _("The request returned a 302 Multiple Choices. This generally "
                "means that you have not included a version indicator in a "
                "request URI.\n\nThe body of response returned:\n%(body)s")


class InvalidContentType(HeatException):
    message = _("Invalid content type %(content_type)s")


class BadRegistryConnectionConfiguration(HeatException):
    message = _("Registry was not configured correctly on API server. "
                "Reason: %(reason)s")


class BadStoreConfiguration(HeatException):
    message = _("Store %(store_name)s could not be configured correctly. "
               "Reason: %(reason)s")


class BadDriverConfiguration(HeatException):
    message = _("Driver %(driver_name)s could not be configured correctly. "
               "Reason: %(reason)s")


class StoreDeleteNotSupported(HeatException):
    message = _("Deleting images from this store is not supported.")


class StoreAddDisabled(HeatException):
    message = _("Configuration for store failed. Adding images to this "
               "store is disabled.")


class InvalidNotifierStrategy(HeatException):
    message = _("'%(strategy)s' is not an available notifier strategy.")


class MaxRedirectsExceeded(HeatException):
    message = _("Maximum redirects (%(redirects)s) was exceeded.")


class InvalidRedirect(HeatException):
    message = _("Received invalid HTTP redirect.")


class NoServiceEndpoint(HeatException):
    message = _("Response from Keystone does not contain a Heat endpoint.")


class RegionAmbiguity(HeatException):
    message = _("Multiple 'image' service matches for region %(region)s. This "
                "generally means that a region is required and you have not "
                "supplied one.")
