# -*- coding: utf-8 -*-
#
# Copyright © 2013 Unitedstack Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""A middleware that turns exceptions into parsable string.

Inspired by Cinder's faultwrapper.
"""

import sys
import traceback

from oslo_config import cfg
from oslo_utils import reflection
import six
import webob

from heat.common import exception
from heat.common import serializers
from heat.common import wsgi


class Fault(object):

    def __init__(self, error):
        self.error = error

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if req.content_type == 'application/xml':
            serializer = serializers.XMLResponseSerializer()
        else:
            serializer = serializers.JSONResponseSerializer()
        resp = webob.Response(request=req)
        default_webob_exc = webob.exc.HTTPInternalServerError()
        resp.status_code = self.error.get('code', default_webob_exc.code)
        serializer.default(resp, self.error)
        return resp


class FaultWrapper(wsgi.Middleware):
    """Replace error body with something the client can parse."""

    error_map = {
        'AttributeError': webob.exc.HTTPBadRequest,
        'ActionInProgress': webob.exc.HTTPConflict,
        'ValueError': webob.exc.HTTPBadRequest,
        'EntityNotFound': webob.exc.HTTPNotFound,
        'NotFound': webob.exc.HTTPNotFound,
        'ResourceActionNotSupported': webob.exc.HTTPBadRequest,
        'InvalidGlobalResource': webob.exc.HTTPInternalServerError,
        'ResourceNotAvailable': webob.exc.HTTPNotFound,
        'PhysicalResourceNameAmbiguity': webob.exc.HTTPBadRequest,
        'PhysicalResourceIDAmbiguity': webob.exc.HTTPBadRequest,
        'InvalidTenant': webob.exc.HTTPForbidden,
        'Forbidden': webob.exc.HTTPForbidden,
        'StackExists': webob.exc.HTTPConflict,
        'StackValidationFailed': webob.exc.HTTPBadRequest,
        'InvalidSchemaError': webob.exc.HTTPBadRequest,
        'InvalidTemplateReference': webob.exc.HTTPBadRequest,
        'InvalidTemplateVersion': webob.exc.HTTPBadRequest,
        'InvalidTemplateSection': webob.exc.HTTPBadRequest,
        'UnknownUserParameter': webob.exc.HTTPBadRequest,
        'RevertFailed': webob.exc.HTTPInternalServerError,
        'StopActionFailed': webob.exc.HTTPInternalServerError,
        'EventSendFailed': webob.exc.HTTPInternalServerError,
        'ServerBuildFailed': webob.exc.HTTPInternalServerError,
        'InvalidEncryptionKey': webob.exc.HTTPInternalServerError,
        'NotSupported': webob.exc.HTTPBadRequest,
        'MissingCredentialError': webob.exc.HTTPBadRequest,
        'UserParameterMissing': webob.exc.HTTPBadRequest,
        'RequestLimitExceeded': webob.exc.HTTPBadRequest,
        'DownloadLimitExceeded': webob.exc.HTTPBadRequest,
        'Invalid': webob.exc.HTTPBadRequest,
        'ResourcePropertyConflict': webob.exc.HTTPBadRequest,
        'PropertyUnspecifiedError': webob.exc.HTTPBadRequest,
        'ObjectFieldInvalid': webob.exc.HTTPBadRequest,
        'ReadOnlyFieldError': webob.exc.HTTPBadRequest,
        'ObjectActionError': webob.exc.HTTPBadRequest,
        'IncompatibleObjectVersion': webob.exc.HTTPBadRequest,
        'OrphanedObjectError': webob.exc.HTTPBadRequest,
        'UnsupportedObjectError': webob.exc.HTTPBadRequest,
        'ResourceTypeUnavailable': webob.exc.HTTPBadRequest,
        'InvalidBreakPointHook': webob.exc.HTTPBadRequest,
        'ImmutableParameterModified': webob.exc.HTTPBadRequest
    }

    def _map_exception_to_error(self, class_exception):
        if class_exception == Exception:
            return webob.exc.HTTPInternalServerError

        if class_exception.__name__ not in self.error_map:
            return self._map_exception_to_error(class_exception.__base__)

        return self.error_map[class_exception.__name__]

    def _error(self, ex):

        trace = None
        traceback_marker = 'Traceback (most recent call last)'
        webob_exc = None
        safe = getattr(ex, 'safe', False)

        if isinstance(ex, exception.HTTPExceptionDisguise):
            # An HTTP exception was disguised so it could make it here
            # let's remove the disguise and set the original HTTP exception
            if cfg.CONF.debug:
                trace = ''.join(traceback.format_tb(ex.tb))
            ex = ex.exc
            webob_exc = ex

        ex_type = reflection.get_class_name(ex, fully_qualified=False)

        is_remote = ex_type.endswith('_Remote')
        if is_remote:
            ex_type = ex_type[:-len('_Remote')]

        full_message = six.text_type(ex)
        if '\n' in full_message and is_remote:
            message, msg_trace = full_message.split('\n', 1)
        elif traceback_marker in full_message:
            message, msg_trace = full_message.split(traceback_marker, 1)
            message = message.rstrip('\n')
            msg_trace = traceback_marker + msg_trace
        else:
            msg_trace = 'None\n'
            if sys.exc_info() != (None, None, None):
                msg_trace = traceback.format_exc()
            message = full_message

        if isinstance(ex, exception.HeatException):
            message = ex.message

        if cfg.CONF.debug and not trace:
            trace = msg_trace

        if not webob_exc:
            webob_exc = self._map_exception_to_error(ex.__class__)

        error = {
            'code': webob_exc.code,
            'title': webob_exc.title,
            'explanation': webob_exc.explanation,
            'error': {
                'type': ex_type,
                'traceback': trace,
            }
        }
        if safe:
            error['error']['message'] = message

        return error

    def process_request(self, req):
        try:
            return req.get_response(self.application)
        except Exception as exc:
            return req.get_response(Fault(self._error(exc)))
