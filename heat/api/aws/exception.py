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

"""Heat API exception subclasses - maps API response errors to AWS Errors"""

import webob.exc
from heat.common import wsgi
import heat.openstack.common.rpc.common as rpc_common


class HeatAPIException(webob.exc.HTTPError):
    '''
    Subclass webob HTTPError so we can correctly serialize the wsgi response
    into the http response body, using the format specified by the request.
    Note this should not be used directly, instead use of of the subclasses
    defined below which map to AWS API errors
    '''
    code = 400
    title = "HeatAPIException"
    explanation = "Generic HeatAPIException, please use specific subclasses!"
    err_type = "Sender"

    def __init__(self, detail=None):
        '''
        Overload HTTPError constructor, so we can create a default serialized
        body.  This is required because not all error responses are processed
        by the wsgi controller (ie auth errors, which are further up the
        paste pipeline.  We serialize in XML by default (as AWS does)
        '''
        webob.exc.HTTPError.__init__(self, detail=detail)
        serializer = wsgi.XMLResponseSerializer()
        serializer.default(self, self.get_unserialized_body())

    def get_unserialized_body(self):
        '''
        Return a dict suitable for serialization in the wsgi controller
        This wraps the exception details in a format which maps to the
        expected format for the AWS API
        '''
        # Note the aws response format specifies a "Code" element which is not
        # the html response code, but the AWS API error code, e.g self.title
        if self.detail:
            message = ":".join([self.explanation, self.detail])
        else:
            message = self.explanation
        return {'ErrorResponse': {'Error': {'Type': self.err_type,
                'Code': self.title, 'Message': message}}}


# Common Error Subclasses:
# As defined in http://docs.amazonwebservices.com/AWSCloudFormation/
# latest/APIReference/CommonErrors.html


class HeatIncompleteSignatureError(HeatAPIException):
    '''
    The request signature does not conform to AWS standards
    '''
    code = 400
    title = "IncompleteSignature"
    explanation = "The request signature does not conform to AWS standards"


class HeatInternalFailureError(HeatAPIException):
    '''
    The request processing has failed due to some unknown error
    '''
    code = 500
    title = "InternalFailure"
    explanation = "The request processing has failed due to an internal error"
    err_type = "Server"


class HeatInvalidActionError(HeatAPIException):
    '''
    The action or operation requested is invalid
    '''
    code = 400
    title = "InvalidAction"
    explanation = "The action or operation requested is invalid"


class HeatInvalidClientTokenIdError(HeatAPIException):
    '''
    The X.509 certificate or AWS Access Key ID provided does not exist
    '''
    code = 403
    title = "InvalidClientTokenId"
    explanation = "The certificate or AWS Key ID provided does not exist"


class HeatInvalidParameterCombinationError(HeatAPIException):
    '''
    Parameters that must not be used together were used together
    '''
    code = 400
    title = "InvalidParameterCombination"
    explanation = "Incompatible parameters were used together"


class HeatInvalidParameterValueError(HeatAPIException):
    '''
    A bad or out-of-range value was supplied for the input parameter
    '''
    code = 400
    title = "InvalidParameterValue"
    explanation = "A bad or out-of-range value was supplied"


class HeatInvalidQueryParameterError(HeatAPIException):
    '''
    AWS query string is malformed, does not adhere to AWS standards
    '''
    code = 400
    title = "InvalidQueryParameter"
    explanation = "AWS query string is malformed, does not adhere to AWS spec"


class HeatMalformedQueryStringError(HeatAPIException):
    '''
    The query string is malformed
    '''
    code = 404
    title = "MalformedQueryString"
    explanation = "The query string is malformed"


class HeatMissingActionError(HeatAPIException):
    '''
    The request is missing an action or operation parameter
    '''
    code = 400
    title = "MissingAction"
    explanation = "The request is missing an action or operation parameter"


class HeatMissingAuthenticationTokenError(HeatAPIException):
    '''
    Request must contain either a valid (registered) AWS Access Key ID
    or X.509 certificate
    '''
    code = 403
    title = "MissingAuthenticationToken"
    explanation = "Does not contain a valid AWS Access Key or certificate"


class HeatMissingParameterError(HeatAPIException):
    '''
    An input parameter that is mandatory for processing the request is missing
    '''
    code = 400
    title = "MissingParameter"
    explanation = "A mandatory input parameter is missing"


class HeatOptInRequiredError(HeatAPIException):
    '''
    The AWS Access Key ID needs a subscription for the service
    '''
    code = 403
    title = "OptInRequired"
    explanation = "The AWS Access Key ID needs a subscription for the service"


class HeatRequestExpiredError(HeatAPIException):
    '''
    Request is past expires date or the request date (either with 15 minute
    padding), or the request date occurs more than 15 minutes in the future
    '''
    code = 400
    title = "RequestExpired"
    explanation = "Request expired or more than 15mins in the future"


class HeatServiceUnavailableError(HeatAPIException):
    '''
    The request has failed due to a temporary failure of the server
    '''
    code = 503
    title = "ServiceUnavailable"
    explanation = "Service temporarily unvavailable"
    err_type = "Server"


class HeatThrottlingError(HeatAPIException):
    '''
    Request was denied due to request throttling
    '''
    code = 400
    title = "Throttling"
    explanation = "Request was denied due to request throttling"


class AlreadyExistsError(HeatAPIException):
    '''
    Resource with the name requested already exists
    '''
    code = 400
    title = 'AlreadyExists'
    explanation = "Resource with the name requested already exists"


# Not documented in the AWS docs, authentication failure errors
class HeatAccessDeniedError(HeatAPIException):
    '''
    This is the response given when authentication fails due to user
    IAM group memberships meaning we deny access
    '''
    code = 403
    title = "AccessDenied"
    explanation = "User is not authorized to perform action"


class HeatSignatureError(HeatAPIException):
    '''
    This is the response given when authentication fails due to
    a bad signature
    '''
    code = 403
    title = "SignatureDoesNotMatch"
    explanation = ("The request signature we calculated does not match the " +
                   "signature you provided")


# Heat-specific errors
class HeatAPINotImplementedError(HeatAPIException):
    '''
    This is the response given when an API action is not yet implemented
    '''
    code = 500
    title = "APINotImplemented"
    explanation = ("The requested action is not yet implemented")
    err_type = "Server"


def map_remote_error(ex):
        """
        Map rpc_common.RemoteError exceptions returned by the engine
        to HeatAPIException subclasses which can be used to return
        properly formatted AWS error responses
        """
        inval_param_errors = (
            'AttributeError',
            'ValueError',
            'InvalidTenant',
            'StackNotFound',
            'ResourceNotFound',
            'ResourceNotAvailable',
            'ResourceTypeNotFound',
            'PhysicalResourceNotFound',
            'WatchRuleNotFound',
            'StackValidationFailed',
            'InvalidTemplateReference',
            'UnknownUserParameter',
            'UserParameterMissing',
            'InvalidTemplateParameter',
        )
        denied_errors = ('Forbidden', 'NotAuthorized')
        already_exists_errors = ('StackExists')

        ex_type = ex.__class__.__name__

        if ex_type.endswith(rpc_common._REMOTE_POSTFIX):
            ex_type = ex_type[:-len(rpc_common._REMOTE_POSTFIX)]

        if ex_type in inval_param_errors:
            return HeatInvalidParameterValueError(detail=str(ex.message))
        elif ex_type in denied_errors:
            return HeatAccessDeniedError(detail=str(ex.message))
        elif ex_type in already_exists_errors:
            return AlreadyExistsError(detail=str(ex.message))
        else:
            # Map everything else to internal server error for now
            return HeatInternalFailureError(detail=str(ex.message))
