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

"""Stack endpoint for Heat CloudFormation v1 API."""

import socket

from oslo_log import log as logging
from oslo_serialization import jsonutils

from heat.api.aws import exception
from heat.api.aws import utils as api_utils
from heat.common import exception as heat_exception
from heat.common.i18n import _
from heat.common import identifier
from heat.common import policy
from heat.common import template_format
from heat.common import urlfetch
from heat.common import wsgi
from heat.rpc import api as rpc_api
from heat.rpc import client as rpc_client

LOG = logging.getLogger(__name__)


class StackController(object):

    """WSGI controller for stacks resource in Heat CloudFormation v1 API.

    Implements the API actions.
    """

    def __init__(self, options):
        self.options = options
        self.rpc_client = rpc_client.EngineClient()
        self.policy = policy.Enforcer(scope='cloudformation')

    def default(self, req, **args):
        raise exception.HeatInvalidActionError()

    def _enforce(self, req, action):
        """Authorize an action against the policy.json and policies in code."""
        try:
            self.policy.enforce(req.context, action, is_registered_policy=True)
        except heat_exception.Forbidden:
            msg = _('Action %s not allowed for user') % action
            raise exception.HeatAccessDeniedError(msg)
        except Exception:
            # We expect policy.enforce to either pass or raise Forbidden
            # however, if anything else happens, we want to raise
            # HeatInternalFailureError, failure to do this results in
            # the user getting a big stacktrace spew as an API response
            msg = _('Error authorizing action %s') % action
            raise exception.HeatInternalFailureError(msg)

    @staticmethod
    def _id_format(resp):
        """Format the StackId field in the response as an ARN.

        Also, process other IDs into the correct format.
        """
        if 'StackId' in resp:
            identity = identifier.HeatIdentifier(**resp['StackId'])
            resp['StackId'] = identity.arn()
        if 'EventId' in resp:
            identity = identifier.EventIdentifier(**resp['EventId'])
            resp['EventId'] = identity.event_id
        return resp

    @staticmethod
    def _extract_user_params(params):
        """Extract a dictionary of user input parameters for the stack.

        In the AWS API parameters, each user parameter appears as two key-value
        pairs with keys of the form below::

          Parameters.member.1.ParameterKey
          Parameters.member.1.ParameterValue
        """
        return api_utils.extract_param_pairs(params,
                                             prefix='Parameters',
                                             keyname='ParameterKey',
                                             valuename='ParameterValue')

    def _get_identity(self, con, stack_name):
        """Generate a stack identifier from the given stack name or ARN.

        In the case of a stack name, the identifier will be looked up in the
        engine over RPC.
        """
        try:
            return dict(identifier.HeatIdentifier.from_arn(stack_name))
        except ValueError:
            return self.rpc_client.identify_stack(con, stack_name)

    def list(self, req):
        """Implements ListStacks API action.

        Lists summary information for all stacks.
        """
        self._enforce(req, 'ListStacks')

        def format_stack_summary(s):
            """Reformat engine output into the AWS "StackSummary" format."""
            # Map the engine-api format to the AWS StackSummary datatype
            keymap = {
                rpc_api.STACK_CREATION_TIME: 'CreationTime',
                rpc_api.STACK_UPDATED_TIME: 'LastUpdatedTime',
                rpc_api.STACK_ID: 'StackId',
                rpc_api.STACK_NAME: 'StackName',
                rpc_api.STACK_STATUS_DATA: 'StackStatusReason',
                rpc_api.STACK_TMPL_DESCRIPTION: 'TemplateDescription',
            }

            result = api_utils.reformat_dict_keys(keymap, s)

            action = s[rpc_api.STACK_ACTION]
            status = s[rpc_api.STACK_STATUS]
            result['StackStatus'] = '_'.join((action, status))

            # AWS docs indicate DeletionTime is omitted for current stacks
            # This is still TODO(unknown) in the engine, we don't keep data for
            # stacks after they are deleted
            if rpc_api.STACK_DELETION_TIME in s:
                result['DeletionTime'] = s[rpc_api.STACK_DELETION_TIME]

            return self._id_format(result)

        con = req.context
        try:
            stack_list = self.rpc_client.list_stacks(con)
        except Exception as ex:
            return exception.map_remote_error(ex)

        res = {'StackSummaries': [format_stack_summary(s) for s in stack_list]}

        return api_utils.format_response('ListStacks', res)

    def describe(self, req):
        """Implements DescribeStacks API action.

        Gets detailed information for a stack (or all stacks).
        """
        self._enforce(req, 'DescribeStacks')

        def format_stack_outputs(o):
            keymap = {
                rpc_api.OUTPUT_DESCRIPTION: 'Description',
                rpc_api.OUTPUT_KEY: 'OutputKey',
                rpc_api.OUTPUT_VALUE: 'OutputValue',
            }

            def replacecolon(d):
                return dict(map(lambda k_v: (k_v[0].replace(':', '.'), k_v[1]),
                                d.items()))

            def transform(attrs):
                """Recursively replace all `:` with `.` in dict keys.

                After that they are not interpreted as xml namespaces.
                """
                new = replacecolon(attrs)
                for key, value in new.items():
                    if isinstance(value, dict):
                        new[key] = transform(value)
                return new

            return api_utils.reformat_dict_keys(keymap, transform(o))

        def format_stack(s):
            """Reformat engine output into the AWS "StackSummary" format."""
            keymap = {
                rpc_api.STACK_CAPABILITIES: 'Capabilities',
                rpc_api.STACK_CREATION_TIME: 'CreationTime',
                rpc_api.STACK_DESCRIPTION: 'Description',
                rpc_api.STACK_DISABLE_ROLLBACK: 'DisableRollback',
                rpc_api.STACK_NOTIFICATION_TOPICS: 'NotificationARNs',
                rpc_api.STACK_PARAMETERS: 'Parameters',
                rpc_api.STACK_ID: 'StackId',
                rpc_api.STACK_NAME: 'StackName',
                rpc_api.STACK_STATUS_DATA: 'StackStatusReason',
                rpc_api.STACK_TIMEOUT: 'TimeoutInMinutes',
            }

            if s[rpc_api.STACK_UPDATED_TIME] is not None:
                keymap[rpc_api.STACK_UPDATED_TIME] = 'LastUpdatedTime'

            result = api_utils.reformat_dict_keys(keymap, s)

            action = s[rpc_api.STACK_ACTION]
            status = s[rpc_api.STACK_STATUS]
            result['StackStatus'] = '_'.join((action, status))

            # Reformat outputs, these are handled separately as they are
            # only present in the engine output for a completely created
            # stack
            result['Outputs'] = []
            if rpc_api.STACK_OUTPUTS in s:
                for o in s[rpc_api.STACK_OUTPUTS]:
                    result['Outputs'].append(format_stack_outputs(o))

            # Reformat Parameters dict-of-dict into AWS API format
            # This is a list-of-dict with nasty "ParameterKey" : key
            # "ParameterValue" : value format.
            result['Parameters'] = [{'ParameterKey': k,
                                    'ParameterValue': v}
                                    for (k, v) in result['Parameters'].items()]

            return self._id_format(result)

        con = req.context
        # If no StackName parameter is passed, we pass None into the engine
        # this returns results for all stacks (visible to this user), which
        # is the behavior described in the AWS DescribeStacks API docs
        try:
            if 'StackName' in req.params:
                identity = self._get_identity(con, req.params['StackName'])
            else:
                identity = None

            stack_list = self.rpc_client.show_stack(con, identity)

        except Exception as ex:
            return exception.map_remote_error(ex)

        res = {'Stacks': [format_stack(s) for s in stack_list]}

        return api_utils.format_response('DescribeStacks', res)

    def _get_template(self, req):
        """Get template file contents, either from local file or URL."""
        if 'TemplateBody' in req.params:
            LOG.debug('TemplateBody ...')
            return req.params['TemplateBody']
        elif 'TemplateUrl' in req.params:
            url = req.params['TemplateUrl']
            LOG.debug('TemplateUrl %s' % url)
            try:
                return urlfetch.get(url)
            except IOError as exc:
                msg = _('Failed to fetch template: %s') % exc
                raise exception.HeatInvalidParameterValueError(detail=msg)

        return None

    CREATE_OR_UPDATE_ACTION = (
        CREATE_STACK, UPDATE_STACK,
    ) = (
        "CreateStack", "UpdateStack",
    )

    def create(self, req):
        self._enforce(req, 'CreateStack')
        return self.create_or_update(req, self.CREATE_STACK)

    def update(self, req):
        self._enforce(req, 'UpdateStack')
        return self.create_or_update(req, self.UPDATE_STACK)

    def create_or_update(self, req, action=None):
        """Implements CreateStack and UpdateStack API actions.

        Create or update stack as defined in template file.
        """
        def extract_args(params):
            """Extract request params and reformat them to match engine API.

            FIXME: we currently only support a subset of
            the AWS defined parameters (both here and in the engine)
            """
            # TODO(shardy) : Capabilities, NotificationARNs
            keymap = {'TimeoutInMinutes': rpc_api.PARAM_TIMEOUT,
                      'DisableRollback': rpc_api.PARAM_DISABLE_ROLLBACK}

            if 'DisableRollback' in params and 'OnFailure' in params:
                msg = _('DisableRollback and OnFailure '
                        'may not be used together')
                raise exception.HeatInvalidParameterCombinationError(
                    detail=msg)

            result = {}
            for k in keymap:
                if k in params:
                    result[keymap[k]] = params[k]

            if 'OnFailure' in params:
                value = params['OnFailure']
                if value == 'DO_NOTHING':
                    result[rpc_api.PARAM_DISABLE_ROLLBACK] = 'true'
                elif value in ('ROLLBACK', 'DELETE'):
                    result[rpc_api.PARAM_DISABLE_ROLLBACK] = 'false'

            return result

        if action not in self.CREATE_OR_UPDATE_ACTION:
            msg = _("Unexpected action %(action)s") % ({'action': action})
            # This should not happen, so return HeatInternalFailureError
            return exception.HeatInternalFailureError(detail=msg)

        engine_action = {self.CREATE_STACK: self.rpc_client.create_stack,
                         self.UPDATE_STACK: self.rpc_client.update_stack}

        con = req.context

        # Extract the stack input parameters
        stack_parms = self._extract_user_params(req.params)

        # Extract any additional arguments ("Request Parameters")
        create_args = extract_args(req.params)

        try:
            templ = self._get_template(req)
        except socket.gaierror:
            msg = _('Invalid Template URL')
            return exception.HeatInvalidParameterValueError(detail=msg)

        if templ is None:
            msg = _("TemplateBody or TemplateUrl were not given.")
            return exception.HeatMissingParameterError(detail=msg)

        try:
            stack = template_format.parse(templ)
        except ValueError:
            msg = _("The Template must be a JSON or YAML document.")
            return exception.HeatInvalidParameterValueError(detail=msg)

        args = {'template': stack,
                'params': stack_parms,
                'files': {},
                'args': create_args}
        try:
            stack_name = req.params['StackName']
            if action == self.CREATE_STACK:
                args['stack_name'] = stack_name
            else:
                args['stack_identity'] = self._get_identity(con, stack_name)

            result = engine_action[action](con, **args)
        except Exception as ex:
            return exception.map_remote_error(ex)

        try:
            identity = identifier.HeatIdentifier(**result)
        except (ValueError, TypeError):
            response = result
        else:
            response = {'StackId': identity.arn()}

        return api_utils.format_response(action, response)

    def cancel_update(self, req):
        action = 'CancelUpdateStack'
        self._enforce(req, action)
        con = req.context
        stack_name = req.params['StackName']
        stack_identity = self._get_identity(con, stack_name)
        try:
            self.rpc_client.stack_cancel_update(
                con, stack_identity=stack_identity, cancel_with_rollback=True)
        except Exception as ex:
            return exception.map_remote_error(ex)

        return api_utils.format_response(action, {})

    def get_template(self, req):
        """Implements the GetTemplate API action.

        Get the template body for an existing stack.
        """
        self._enforce(req, 'GetTemplate')

        con = req.context
        try:
            identity = self._get_identity(con, req.params['StackName'])
            templ = self.rpc_client.get_template(con, identity)
        except Exception as ex:
            return exception.map_remote_error(ex)

        return api_utils.format_response('GetTemplate',
                                         {'TemplateBody': templ})

    def estimate_template_cost(self, req):
        """Implements the EstimateTemplateCost API action.

        Get the estimated monthly cost of a template.
        """
        self._enforce(req, 'EstimateTemplateCost')

        return api_utils.format_response('EstimateTemplateCost',
                                         {'Url':
                                          'http://en.wikipedia.org/wiki/Gratis'
                                          }
                                         )

    def validate_template(self, req):
        """Implements the ValidateTemplate API action.

        Validates the specified template.
        """
        self._enforce(req, 'ValidateTemplate')

        con = req.context
        try:
            templ = self._get_template(req)
        except socket.gaierror:
            msg = _('Invalid Template URL')
            return exception.HeatInvalidParameterValueError(detail=msg)
        if templ is None:
            msg = _("TemplateBody or TemplateUrl were not given.")
            return exception.HeatMissingParameterError(detail=msg)

        try:
            template = template_format.parse(templ)
        except ValueError:
            msg = _("The Template must be a JSON or YAML document.")
            return exception.HeatInvalidParameterValueError(detail=msg)

        LOG.info('validate_template')

        def format_validate_parameter(key, value):
            """Reformat engine output into AWS "ValidateTemplate" format."""

            return {
                'ParameterKey': key,
                'DefaultValue': value.get(rpc_api.PARAM_DEFAULT, ''),
                'Description': value.get(rpc_api.PARAM_DESCRIPTION, ''),
                'NoEcho': value.get(rpc_api.PARAM_NO_ECHO, 'false')
            }

        try:
            res = self.rpc_client.validate_template(con, template)
            if 'Error' in res:
                return api_utils.format_response('ValidateTemplate',
                                                 res['Error'])

            res['Parameters'] = [format_validate_parameter(k, v)
                                 for k, v in res['Parameters'].items()]
            return api_utils.format_response('ValidateTemplate', res)
        except Exception as ex:
            return exception.map_remote_error(ex)

    def delete(self, req):
        """Implements the DeleteStack API action.

        Deletes the specified stack.
        """
        self._enforce(req, 'DeleteStack')

        con = req.context
        try:
            identity = self._get_identity(con, req.params['StackName'])
            res = self.rpc_client.delete_stack(con, identity, cast=False)

        except Exception as ex:
            return exception.map_remote_error(ex)

        if res is None:
            return api_utils.format_response('DeleteStack', '')
        else:
            return api_utils.format_response('DeleteStack', res['Error'])

    def events_list(self, req):
        """Implements the DescribeStackEvents API action.

        Returns events related to a specified stack (or all stacks).
        """
        self._enforce(req, 'DescribeStackEvents')

        def format_stack_event(e):
            """Reformat engine output into AWS "StackEvent" format."""
            keymap = {
                rpc_api.EVENT_ID: 'EventId',
                rpc_api.EVENT_RES_NAME: 'LogicalResourceId',
                rpc_api.EVENT_RES_PHYSICAL_ID: 'PhysicalResourceId',
                rpc_api.EVENT_RES_PROPERTIES: 'ResourceProperties',
                rpc_api.EVENT_RES_STATUS_DATA: 'ResourceStatusReason',
                rpc_api.EVENT_RES_TYPE: 'ResourceType',
                rpc_api.EVENT_STACK_ID: 'StackId',
                rpc_api.EVENT_STACK_NAME: 'StackName',
                rpc_api.EVENT_TIMESTAMP: 'Timestamp',
            }

            result = api_utils.reformat_dict_keys(keymap, e)
            action = e[rpc_api.EVENT_RES_ACTION]
            status = e[rpc_api.EVENT_RES_STATUS]
            result['ResourceStatus'] = '_'.join((action, status))
            result['ResourceProperties'] = jsonutils.dumps(result[
                'ResourceProperties'])

            return self._id_format(result)

        con = req.context
        stack_name = req.params.get('StackName')
        try:
            identity = stack_name and self._get_identity(con, stack_name)
            events = self.rpc_client.list_events(con, identity)
        except Exception as ex:
            return exception.map_remote_error(ex)

        result = [format_stack_event(e) for e in events]

        return api_utils.format_response('DescribeStackEvents',
                                         {'StackEvents': result})

    @staticmethod
    def _resource_status(res):
        action = res[rpc_api.RES_ACTION]
        status = res[rpc_api.RES_STATUS]
        return '_'.join((action, status))

    def describe_stack_resource(self, req):
        """Implements the DescribeStackResource API action.

        Return the details of the given resource belonging to the given stack.
        """
        self._enforce(req, 'DescribeStackResource')

        def format_resource_detail(r):
            # Reformat engine output into the AWS "StackResourceDetail" format
            keymap = {
                rpc_api.RES_DESCRIPTION: 'Description',
                rpc_api.RES_UPDATED_TIME: 'LastUpdatedTimestamp',
                rpc_api.RES_NAME: 'LogicalResourceId',
                rpc_api.RES_METADATA: 'Metadata',
                rpc_api.RES_PHYSICAL_ID: 'PhysicalResourceId',
                rpc_api.RES_STATUS_DATA: 'ResourceStatusReason',
                rpc_api.RES_TYPE: 'ResourceType',
                rpc_api.RES_STACK_ID: 'StackId',
                rpc_api.RES_STACK_NAME: 'StackName',
            }

            result = api_utils.reformat_dict_keys(keymap, r)

            result['ResourceStatus'] = self._resource_status(r)

            return self._id_format(result)

        con = req.context

        try:
            identity = self._get_identity(con, req.params['StackName'])
            resource_details = self.rpc_client.describe_stack_resource(
                con,
                stack_identity=identity,
                resource_name=req.params.get('LogicalResourceId'))

        except Exception as ex:
            return exception.map_remote_error(ex)

        result = format_resource_detail(resource_details)

        return api_utils.format_response('DescribeStackResource',
                                         {'StackResourceDetail': result})

    def describe_stack_resources(self, req):
        """Implements the DescribeStackResources API action.

        Return details of resources specified by the parameters.

        `StackName`: returns all resources belonging to the stack.

        `PhysicalResourceId`: returns all resources belonging to the stack this
        resource is associated with.

        Only one of the parameters may be specified.

        Optional parameter:

        `LogicalResourceId`: filter the resources list by the logical resource
        id.
        """
        self._enforce(req, 'DescribeStackResources')

        def format_stack_resource(r):
            """Reformat engine output into AWS "StackResource" format."""
            keymap = {
                rpc_api.RES_DESCRIPTION: 'Description',
                rpc_api.RES_NAME: 'LogicalResourceId',
                rpc_api.RES_PHYSICAL_ID: 'PhysicalResourceId',
                rpc_api.RES_STATUS_DATA: 'ResourceStatusReason',
                rpc_api.RES_TYPE: 'ResourceType',
                rpc_api.RES_STACK_ID: 'StackId',
                rpc_api.RES_STACK_NAME: 'StackName',
                rpc_api.RES_UPDATED_TIME: 'Timestamp',
            }

            result = api_utils.reformat_dict_keys(keymap, r)

            result['ResourceStatus'] = self._resource_status(r)

            return self._id_format(result)

        con = req.context
        stack_name = req.params.get('StackName')
        physical_resource_id = req.params.get('PhysicalResourceId')
        if stack_name and physical_resource_id:
            msg = 'Use `StackName` or `PhysicalResourceId` but not both'
            return exception.HeatInvalidParameterCombinationError(detail=msg)

        try:
            if stack_name is not None:
                identity = self._get_identity(con, stack_name)
            else:
                identity = self.rpc_client.find_physical_resource(
                    con,
                    physical_resource_id=physical_resource_id)
            resources = self.rpc_client.describe_stack_resources(
                con,
                stack_identity=identity,
                resource_name=req.params.get('LogicalResourceId'))

        except Exception as ex:
            return exception.map_remote_error(ex)

        result = [format_stack_resource(r) for r in resources]

        return api_utils.format_response('DescribeStackResources',
                                         {'StackResources': result})

    def list_stack_resources(self, req):
        """Implements the ListStackResources API action.

        Return summary of the resources belonging to the specified stack.
        """
        self._enforce(req, 'ListStackResources')

        def format_resource_summary(r):
            """Reformat engine output to AWS "StackResourceSummary" format."""
            keymap = {
                rpc_api.RES_UPDATED_TIME: 'LastUpdatedTimestamp',
                rpc_api.RES_NAME: 'LogicalResourceId',
                rpc_api.RES_PHYSICAL_ID: 'PhysicalResourceId',
                rpc_api.RES_STATUS_DATA: 'ResourceStatusReason',
                rpc_api.RES_TYPE: 'ResourceType',
            }

            result = api_utils.reformat_dict_keys(keymap, r)

            result['ResourceStatus'] = self._resource_status(r)

            return result

        con = req.context

        try:
            identity = self._get_identity(con, req.params['StackName'])
            resources = self.rpc_client.list_stack_resources(
                con,
                stack_identity=identity)
        except Exception as ex:
            return exception.map_remote_error(ex)

        summaries = [format_resource_summary(r) for r in resources]

        return api_utils.format_response('ListStackResources',
                                         {'StackResourceSummaries': summaries})


def create_resource(options):
    """Stacks resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    return wsgi.Resource(StackController(options), deserializer)
