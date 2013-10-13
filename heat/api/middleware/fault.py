# -*- encoding: utf-8 -*-
#
# Copyright © 2013 Unitedstack Inc.
#
# Author: Jianing YANG (jianingy@unitedstack.com)
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

"""A middleware that turns exceptions into parsable string. Inspired by
Cinder's faultwrapper
"""

import traceback
import webob
from oslo.config import cfg

cfg.CONF.import_opt('debug', 'heat.openstack.common.log')

from heat.common import exception
from heat.openstack.common import log as logging
import heat.openstack.common.rpc.common as rpc_common

from heat.common import wsgi

logger = logging.getLogger(__name__)


class Fault(object):

    def __init__(self, error):
        self.error = error

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if req.content_type == 'application/xml':
            serializer = wsgi.XMLResponseSerializer()
        else:
            serializer = wsgi.JSONResponseSerializer()
        resp = webob.Response(request=req)
        default_webob_exc = webob.exc.HTTPInternalServerError()
        resp.status_code = self.error.get('code', default_webob_exc.code)
        serializer.default(resp, self.error)
        return resp


class FaultWrapper(wsgi.Middleware):
    """Replace error body with something the client can parse."""

    error_map = {
        'AttributeError': webob.exc.HTTPBadRequest,
        'ValueError': webob.exc.HTTPBadRequest,
        'StackNotFound': webob.exc.HTTPNotFound,
        'ResourceNotFound': webob.exc.HTTPNotFound,
        'ResourceTypeNotFound': webob.exc.HTTPNotFound,
        'ResourceNotAvailable': webob.exc.HTTPNotFound,
        'PhysicalResourceNotFound': webob.exc.HTTPNotFound,
        'InvalidTenant': webob.exc.HTTPForbidden,
        'StackExists': webob.exc.HTTPConflict,
        'StackValidationFailed': webob.exc.HTTPBadRequest,
        'InvalidTemplateReference': webob.exc.HTTPBadRequest,
        'UnknownUserParameter': webob.exc.HTTPBadRequest,
        'RevertFailed': webob.exc.HTTPInternalServerError,
        'ServerBuildFailed': webob.exc.HTTPInternalServerError,
        'NotSupported': webob.exc.HTTPBadRequest,
        'MissingCredentialError': webob.exc.HTTPBadRequest,
        'UserParameterMissing': webob.exc.HTTPBadRequest,
        'RequestLimitExceeded': webob.exc.HTTPBadRequest,
        'InvalidTemplateParameter': webob.exc.HTTPBadRequest,
    }

    def _error(self, ex):

        trace = None
        webob_exc = None
        if isinstance(ex, exception.HTTPExceptionDisguise):
            # An HTTP exception was disguised so it could make it here
            # let's remove the disguise and set the original HTTP exception
            if cfg.CONF.debug:
                trace = ''.join(traceback.format_tb(ex.tb))
            ex = ex.exc
            webob_exc = ex

        ex_type = ex.__class__.__name__

        if ex_type.endswith(rpc_common._REMOTE_POSTFIX):
            ex_type = ex_type[:-len(rpc_common._REMOTE_POSTFIX)]

        message = unicode(ex.message)

        if cfg.CONF.debug and not trace:
            trace = unicode(ex)
            if trace.find('\n') > -1:
                unused, trace = trace.split('\n', 1)
            else:
                trace = traceback.format_exc()

        if not webob_exc:
            webob_exc = self.error_map.get(ex_type,
                                           webob.exc.HTTPInternalServerError)

        error = {
            'code': webob_exc.code,
            'title': webob_exc.title,
            'explanation': webob_exc.explanation,
            'error': {
                'message': message,
                'type': ex_type,
                'traceback': trace,
            }
        }

        return error

    def process_request(self, req):
        try:
            return req.get_response(self.application)
        except Exception as exc:
            return req.get_response(Fault(self._error(exc)))
