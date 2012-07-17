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

"""
/stack endpoint for heat v1 API
"""
import httplib
import json
import os
import socket
import sys
import re
import urlparse
import webob
from heat.api.v1 import exception
from heat.common import wsgi
from heat.common import config
from heat.common import context
from heat import utils
import heat.engine.api as engine_api

from heat.openstack.common import rpc
import heat.openstack.common.rpc.common as rpc_common
from heat.openstack.common import log as logging

logger = logging.getLogger('heat.api.v1.stacks')


class StackController(object):

    """
    WSGI controller for stacks resource in heat v1 API
    Implements the API actions
    """

    def __init__(self, options):
        self.options = options

    def _stackid_addprefix(self, resp):
        """
        Add a host:port:stack prefix, this formats the StackId in the response
        more like the AWS spec
        """
        if 'StackId' in resp:
            hostportprefix = ":".join([socket.gethostname(),
                str(self.options.bind_port), "stack"])
            resp['StackId'] = "/".join([hostportprefix, resp['StackName'],
                                       str(resp['StackId'])])
        return resp

    def _format_response(self, action, response):
        """
        Format response from engine into API format
        """
        return {'%sResponse' % action: {'%sResult' % action: response}}

    def _remote_error(self, ex):
        """
        Map rpc_common.RemoteError exceptions returned by the engine
        to HeatAPIException subclasses which can be used to return
        properly formatted AWS error responses
        """
        if ex.exc_type == 'AttributeError':
            # Attribute error, bad user data, ex.value should tell us why
            return exception.HeatInvalidParameterValueError(detail=ex.value)
        else:
            # Map everything else to internal server error for now
            # FIXME : further investigation into engine errors required
            return exception.HeatInternalFailureError(detail=ex.value)

    @staticmethod
    def _extract_user_params(params):
        """
        Extract a dictionary of user input parameters for the stack

        In the AWS API parameters, each user parameter appears as two key-value
        pairs with keys of the form below:

        Parameters.member.1.ParameterKey
        Parameters.member.1.ParameterValue

        We reformat this into a normal dict here to match the heat
        engine API expected format

        Note this implemented outside of "create" as it will also be
        used by update (and EstimateTemplateCost if appropriate..)
        """
        # Define the AWS key format to extract
        PARAM_KEYS = (
        PARAM_USER_KEY_re,
        PARAM_USER_VALUE_fmt,
        ) = (
        re.compile(r'Parameters\.member\.(.*?)\.ParameterKey$'),
        'Parameters.member.%s.ParameterValue',
        )

        def get_param_pairs():
            for k in params:
                keymatch = PARAM_USER_KEY_re.match(k)
                if keymatch:
                    key = params[k]
                    v = PARAM_USER_VALUE_fmt % keymatch.group(1)
                    try:
                        value = params[v]
                    except KeyError:
                        logger.error('Could not apply parameter %s' % key)

                    yield (key, value)

        return dict(get_param_pairs())

    @staticmethod
    def _reformat_dict_keys(keymap={}, inputdict={}):
        '''
        Utility function for mapping one dict format to another
        '''
        result = {}
        for key in keymap:
            result[keymap[key]] = inputdict[key]
        return result

    def list(self, req):
        """
        Implements ListStacks API action
        Lists summary information for all stacks
        """

        def format_stack_summary(s):
            """
            Reformat engine output into the AWS "StackSummary" format
            """
            # Map the engine-api format to the AWS StackSummary datatype
            keymap = {
                engine_api.STACK_CREATION_TIME: 'CreationTime',
                engine_api.STACK_UPDATED_TIME: 'LastUpdatedTime',
                engine_api.STACK_ID: 'StackId',
                engine_api.STACK_NAME: 'StackName',
                engine_api.STACK_STATUS: 'StackStatus',
                engine_api.STACK_STATUS_DATA: 'StackStatusReason',
                engine_api.STACK_TMPL_DESCRIPTION: 'TemplateDescription',
            }

            result = self._reformat_dict_keys(keymap, s)

            # AWS docs indicate DeletionTime is ommitted for current stacks
            # This is still TODO in the engine, we don't keep data for
            # stacks after they are deleted
            if engine_api.STACK_DELETION_TIME in s:
                result['DeletionTime'] = s[engine_api.STACK_DELETION_TIME]

            return self._stackid_addprefix(result)

        con = req.context
        parms = dict(req.params)

        try:
            # Note show_stack returns details for all stacks when called with
            # no stack_name, we only use a subset of the result here though
            stack_list = rpc.call(con, 'engine',
                              {'method': 'show_stack',
                               'args': {'stack_name': None,
                                'params': parms}})
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        res = {'StackSummaries': [format_stack_summary(s)
                                   for s in stack_list['stacks']]}

        return self._format_response('ListStacks', res)

    def describe(self, req):
        """
        Implements DescribeStacks API action
        Gets detailed information for a stack (or all stacks)
        """
        def format_stack_outputs(o):
            keymap = {
                engine_api.OUTPUT_DESCRIPTION: 'Description',
                engine_api.OUTPUT_KEY: 'OutputKey',
                engine_api.OUTPUT_VALUE: 'OutputValue',
            }

            return self._reformat_dict_keys(keymap, o)

        def format_stack(s):
            """
            Reformat engine output into the AWS "StackSummary" format
            """
            keymap = {
                engine_api.STACK_CAPABILITIES: 'Capabilities',
                engine_api.STACK_CREATION_TIME: 'CreationTime',
                engine_api.STACK_DESCRIPTION: 'Description',
                engine_api.STACK_DISABLE_ROLLBACK: 'DisableRollback',
                engine_api.STACK_UPDATED_TIME: 'LastUpdatedTime',
                engine_api.STACK_NOTIFICATION_TOPICS: 'NotificationARNs',
                engine_api.STACK_PARAMETERS: 'Parameters',
                engine_api.STACK_ID: 'StackId',
                engine_api.STACK_NAME: 'StackName',
                engine_api.STACK_STATUS: 'StackStatus',
                engine_api.STACK_STATUS_DATA: 'StackStatusReason',
                engine_api.STACK_TIMEOUT: 'TimeoutInMinutes',
            }

            result = self._reformat_dict_keys(keymap, s)

            # Reformat outputs, these are handled separately as they are
            # only present in the engine output for a completely created
            # stack
            result['Outputs'] = []
            if engine_api.STACK_OUTPUTS in s:
                for o in s[engine_api.STACK_OUTPUTS]:
                    result['Outputs'].append(format_stack_outputs(o))

            # Reformat Parameters dict-of-dict into AWS API format
            # This is a list-of-dict with nasty "ParameterKey" : key
            # "ParameterValue" : value format.
            result['Parameters'] = [{'ParameterKey':k,
                'ParameterValue':v.get('Default')}
                for (k, v) in result['Parameters'].items()]

            return self._stackid_addprefix(result)

        con = req.context
        parms = dict(req.params)

        # If no StackName parameter is passed, we pass None into the engine
        # this returns results for all stacks (visible to this user), which
        # is the behavior described in the AWS DescribeStacks API docs
        stack_name = None
        if 'StackName' in req.params:
            stack_name = req.params['StackName']

        try:
            stack_list = rpc.call(con, 'engine',
                              {'method': 'show_stack',
                               'args': {'stack_name': stack_name,
                                'params': parms}})

        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        res = {'Stacks': [format_stack(s) for s in stack_list['stacks']]}

        return self._format_response('DescribeStacks', res)

    def _get_template(self, req):
        """
        Get template file contents, either from local file or URL
        """
        if 'TemplateBody' in req.params:
            logger.info('TemplateBody ...')
            return req.params['TemplateBody']
        elif 'TemplateUrl' in req.params:
            logger.info('TemplateUrl %s' % req.params['TemplateUrl'])
            url = urlparse.urlparse(req.params['TemplateUrl'])
            if url.scheme == 'https':
                conn = httplib.HTTPSConnection(url.netloc)
            else:
                conn = httplib.HTTPConnection(url.netloc)
            conn.request("GET", url.path)
            r1 = conn.getresponse()
            logger.info('status %d' % r1.status)
            if r1.status == 200:
                data = r1.read()
                conn.close()
            else:
                data = None
            return data

        return None

    CREATE_OR_UPDATE_ACTION = (
        CREATE_STACK, UPDATE_STACK
        ) = (
        "CreateStack", "UpdateStack")

    def create(self, req):
        return self.create_or_update(req, self.CREATE_STACK)

    def update(self, req):
        return self.create_or_update(req, self.UPDATE_STACK)

    def create_or_update(self, req, action=None):
        """
        Implements CreateStack and UpdateStack API actions
        Create or update stack as defined in template file
        """
        def extract_args(params):
            """
            Extract request parameters/arguments and reformat them to match
            the engine API.  FIXME: we currently only support a subset of
            the AWS defined parameters (both here and in the engine)
            """
            # TODO : Capabilities, DisableRollback, NotificationARNs
            keymap = {'TimeoutInMinutes': engine_api.PARAM_TIMEOUT, }

            result = {}
            for k in keymap:
                if k in req.params:
                    result[keymap[k]] = params[k]

            return result

        if action not in self.CREATE_OR_UPDATE_ACTION:
            msg = _("Unexpected action %s" % action)
            # This should not happen, so return HeatInternalFailureError
            return exception.HeatInternalFailureError(detail=msg)

        engine_action = {self.CREATE_STACK: "create_stack",
                         self.UPDATE_STACK: "update_stack"}

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
            stack = json.loads(templ)
        except ValueError:
            msg = _("The Template must be a JSON document.")
            return exception.HeatInvalidParameterValueError(detail=msg)

        try:
            res = rpc.call(con, 'engine',
                            {'method': engine_action[action],
                             'args': {'stack_name': req.params['StackName'],
                                      'template': stack,
                                      'params': stack_parms,
                                      'args': create_args}})
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        return self._format_response(action, self._stackid_addprefix(res))

    def get_template(self, req):
        """
        Implements the GetTemplate API action
        Get the template body for an existing stack
        """

        con = req.context
        parms = dict(req.params)

        logger.info('get_template')
        try:
            templ = rpc.call(con, 'engine',
                             {'method': 'get_template',
                              'args': {'stack_name': req.params['StackName'],
                                       'params': parms}})
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if templ is None:
            msg = _('stack not not found')
            return exception.HeatInvalidParameterValueError(detail=msg)

        return self._format_response('GetTemplate', {'TemplateBody': templ})

    def estimate_template_cost(self, req):
        """
        Implements the EstimateTemplateCost API action
        Get the estimated monthly cost of a template
        """
        return self._format_response('EstimateTemplateCost',
            {'Url': 'http://en.wikipedia.org/wiki/Gratis'})

    def validate_template(self, req):
        """
        Implements the ValidateTemplate API action
        Validates the specified template
        """

        con = req.context
        parms = dict(req.params)

        try:
            templ = self._get_template(req)
        except socket.gaierror:
            msg = _('Invalid Template URL')
            return exception.HeatInvalidParameterValueError(detail=msg)
        if templ is None:
            msg = _("TemplateBody or TemplateUrl were not given.")
            return exception.HeatMissingParameterError(detail=msg)

        try:
            stack = json.loads(templ)
        except ValueError:
            msg = _("The Template must be a JSON document.")
            return exception.HeatInvalidParameterValueError(detail=msg)

        logger.info('validate_template')
        try:
            return rpc.call(con, 'engine',
                            {'method': 'validate_template',
                             'args': {'template': stack,
                                      'params': parms}})
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

    def delete(self, req):
        """
        Implements the DeleteStack API action
        Deletes the specified stack
        """
        con = req.context
        parms = dict(req.params)

        try:
            res = rpc.call(con, 'engine',
                       {'method': 'delete_stack',
                        'args': {'stack_name': req.params['StackName'],
                        'params': parms}})

        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        if res is None:
            return self._format_response('DeleteStack', '')
        else:
            return self._format_response('DeleteStack', res['Error'])

    def events_list(self, req):
        """
        Implements the DescribeStackEvents API action
        Returns events related to a specified stack (or all stacks)
        """
        def format_stack_event(e):
            """
            Reformat engine output into the AWS "StackEvent" format
            """
            keymap = {
                engine_api.EVENT_ID: 'EventId',
                engine_api.EVENT_RES_NAME: 'LogicalResourceId',
                engine_api.EVENT_RES_PHYSICAL_ID: 'PhysicalResourceId',
                engine_api.EVENT_RES_PROPERTIES: 'ResourceProperties',
                engine_api.EVENT_RES_STATUS: 'ResourceStatus',
                engine_api.EVENT_RES_STATUS_DATA: 'ResourceStatusData',
                engine_api.EVENT_RES_TYPE: 'ResourceType',
                engine_api.EVENT_STACK_ID: 'StackId',
                engine_api.EVENT_STACK_NAME: 'StackName',
                engine_api.EVENT_TIMESTAMP: 'Timestamp',
            }

            result = self._reformat_dict_keys(keymap, e)

            return self._stackid_addprefix(result)

        con = req.context
        parms = dict(req.params)

        stack_name = req.params.get('StackName', None)
        try:
            event_res = rpc.call(con, 'engine',
                             {'method': 'list_events',
                              'args': {'stack_name': stack_name,
                              'params': parms}})
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        events = 'Error' not in event_res and event_res['events'] or []

        result = [format_stack_event(e) for e in events]

        return self._format_response('DescribeStackEvents',
            {'StackEvents': result})

    def describe_stack_resource(self, req):
        """
        Implements the DescribeStackResource API action
        Return the details of the given resource belonging to the given stack.
        """

        def format_resource_detail(r):
            """
            Reformat engine output into the AWS "StackResourceDetail" format
            """
            keymap = {
                engine_api.RES_DESCRIPTION: 'Description',
                engine_api.RES_UPDATED_TIME: 'LastUpdatedTimestamp',
                engine_api.RES_NAME: 'LogicalResourceId',
                engine_api.RES_METADATA: 'Metadata',
                engine_api.RES_PHYSICAL_ID: 'PhysicalResourceId',
                engine_api.RES_STATUS: 'ResourceStatus',
                engine_api.RES_STATUS_DATA: 'ResourceStatusReason',
                engine_api.RES_TYPE: 'ResourceType',
                engine_api.RES_STACK_ID: 'StackId',
                engine_api.RES_STACK_NAME: 'StackName',
            }

            result = self._reformat_dict_keys(keymap, r)

            return self._stackid_addprefix(result)

        con = req.context
        args = {
            'stack_name': req.params.get('StackName'),
            'resource_name': req.params.get('LogicalResourceId'),
        }

        try:
            resource_details = rpc.call(con, 'engine',
                              {'method': 'describe_stack_resource',
                               'args': args})

        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        result = format_resource_detail(resource_details)

        return self._format_response('DescribeStackResource',
            {'StackResourceDetail': result})

    def describe_stack_resources(self, req):
        """
        Implements the DescribeStackResources API action
        Return details of resources specified by the parameters.

        `StackName`: returns all resources belonging to the stack
        `PhysicalResourceId`: returns all resources belonging to the stack this
                              resource is associated with.

        Only one of the parameters may be specified.

        Optional parameter:

        `LogicalResourceId`: filter the resources list by the logical resource
        id.
        """

        def format_stack_resource(r):
            """
            Reformat engine output into the AWS "StackResource" format
            """
            keymap = {
                engine_api.RES_DESCRIPTION: 'Description',
                engine_api.RES_NAME: 'LogicalResourceId',
                engine_api.RES_PHYSICAL_ID: 'PhysicalResourceId',
                engine_api.RES_STATUS: 'ResourceStatus',
                engine_api.RES_STATUS_DATA: 'ResourceStatusReason',
                engine_api.RES_TYPE: 'ResourceType',
                engine_api.RES_STACK_ID: 'StackId',
                engine_api.RES_STACK_NAME: 'StackName',
                engine_api.RES_UPDATED_TIME: 'Timestamp',
            }

            result = self._reformat_dict_keys(keymap, r)

            return self._stackid_addprefix(result)

        con = req.context
        stack_name = req.params.get('StackName')
        physical_resource_id = req.params.get('PhysicalResourceId')
        if stack_name and physical_resource_id:
            msg = 'Use `StackName` or `PhysicalResourceId` but not both'
            return exception.HeatInvalidParameterCombinationError(detail=msg)

        args = {
            'stack_name': stack_name,
            'physical_resource_id': physical_resource_id,
            'logical_resource_id': req.params.get('LogicalResourceId'),
        }

        try:
            resources = rpc.call(con, 'engine',
                              {'method': 'describe_stack_resources',
                               'args': args})

        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        result = [format_stack_resource(r) for r in resources]

        return self._format_response('DescribeStackResources',
            {'StackResources': result})

    def list_stack_resources(self, req):
        """
        Implements the ListStackResources API action
        Return summary of the resources belonging to the specified stack.
        """
        def format_resource_summary(r):
            """
            Reformat engine output into the AWS "StackResourceSummary" format
            """
            keymap = {
                engine_api.RES_UPDATED_TIME: 'LastUpdatedTimestamp',
                engine_api.RES_NAME: 'LogicalResourceId',
                engine_api.RES_PHYSICAL_ID: 'PhysicalResourceId',
                engine_api.RES_STATUS: 'ResourceStatus',
                engine_api.RES_STATUS_DATA: 'ResourceStatusReason',
                engine_api.RES_TYPE: 'ResourceType',
            }

            return self._reformat_dict_keys(keymap, r)

        con = req.context

        try:
            resources = rpc.call(con, 'engine', {
                'method': 'list_stack_resources',
                'args': {'stack_name': req.params.get('StackName')}
            })
        except rpc_common.RemoteError as ex:
            return self._remote_error(ex)

        summaries = [format_resource_summary(r) for r in resources]

        return self._format_response('ListStackResources',
            {'StackResourceSummaries': summaries})


def create_resource(options):
    """
    Stacks resource factory method.
    """
    deserializer = wsgi.JSONRequestDeserializer()
    return wsgi.Resource(StackController(options), deserializer)
