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
Client classes for callers of a heat system
"""

from lxml import etree
from heat.common import client as base_client
from heat.common import exception

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


SUPPORTED_PARAMS = ('StackName', 'TemplateBody', 'TemplateUrl',
                    'NotificationARNs', 'Parameters', 'Version',
                    'SignatureVersion', 'Timestamp', 'AWSAccessKeyId',
                    'Signature', 'TimeoutInMinutes',
                    'LogicalResourceId', 'PhysicalResourceId', 'NextToken',
                    )


class V1Client(base_client.BaseClient):

    """Main client class for accessing heat resources"""

    DEFAULT_DOC_ROOT = "/v1"

    def _insert_common_parameters(self, params):
        params['Version'] = '2010-05-15'
        params['SignatureVersion'] = '2'
        params['SignatureMethod'] = 'HmacSHA256'

    def stack_request(self, action, method, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)
        params['Action'] = action
        headers = {'X-Auth-User': self.creds['username'],
                   'X-Auth-Key': self.creds['password']}

        res = self.do_request(method, "/", params=params, headers=headers)
        doc = etree.fromstring(res.read())
        return etree.tostring(doc, pretty_print=True)

    def list_stacks(self, **kwargs):
        return self.stack_request("ListStacks", "GET", **kwargs)

    def describe_stacks(self, **kwargs):
        return self.stack_request("DescribeStacks", "GET", **kwargs)

    def create_stack(self, **kwargs):
        return self.stack_request("CreateStack", "POST", **kwargs)

    def update_stack(self, **kwargs):
        return self.stack_request("UpdateStack", "POST", **kwargs)

    def delete_stack(self, **kwargs):
        return self.stack_request("DeleteStack", "GET", **kwargs)

    def list_stack_events(self, **kwargs):
        return self.stack_request("DescribeStackEvents", "GET", **kwargs)

    def describe_stack_resource(self, **kwargs):
        return self.stack_request("DescribeStackResource", "GET", **kwargs)

    def describe_stack_resources(self, **kwargs):
        for lookup_key in ['StackName', 'PhysicalResourceId']:
            lookup_value = kwargs['NameOrPid']
            parameters = {
                lookup_key: lookup_value,
                'LogicalResourceId': kwargs['LogicalResourceId']}
            try:
                result = self.stack_request("DescribeStackResources", "GET",
                                            **parameters)
            except Exception:
                logger.debug("Failed to lookup resource details with key %s:%s"
                             % (lookup_key, lookup_value))
            else:
                logger.debug("Got lookup resource details with key %s:%s" %
                             (lookup_key, lookup_value))
                return result

    def list_stack_resources(self, **kwargs):
        return self.stack_request("ListStackResources", "GET", **kwargs)

    def validate_template(self, **kwargs):
        return self.stack_request("ValidateTemplate", "GET", **kwargs)

    def get_template(self, **kwargs):
        return self.stack_request("GetTemplate", "GET", **kwargs)

    def estimate_template_cost(self, **kwargs):
        return self.stack_request("EstimateTemplateCost", "GET", **kwargs)

    # Dummy print functions for alignment with the boto-based client
    # which has to extract class fields for printing, we could also
    # align output format here by decoding the XML/JSON
    def format_stack_event(self, event):
        return str(event)

    def format_stack(self, stack):
        return str(stack)

    def format_stack_resource(self, res):
        return str(res)

    def format_stack_resource_summary(self, res):
        return str(res)

    def format_stack_summary(self, summary):
        return str(summary)

    def format_stack_resource_detail(self, res):
        return str(res)

    def format_template(self, template):
        return str(template)

    def format_parameters(self, options):
        '''
        Reformat parameters into dict of format expected by the API
        '''
        parameters = {}
        if options.parameters:
            for count, p in enumerate(options.parameters.split(';'), 1):
                (n, v) = p.split('=')
                parameters['Parameters.member.%d.ParameterKey' % count] = n
                parameters['Parameters.member.%d.ParameterValue' % count] = v
        return parameters


HeatClient = V1Client


def get_client(host, port=None, username=None,
               password=None, tenant=None,
               auth_url=None, auth_strategy=None,
               auth_token=None, region=None,
               is_silent_upload=False, insecure=False):
    """
    Returns a new client heat client object based on common kwargs.
    If an option isn't specified falls back to common environment variable
    defaults.
    """

    if auth_url:
        force_strategy = 'keystone'
    else:
        force_strategy = None

    creds = dict(username=username,
                 password=password,
                 tenant=tenant,
                 auth_url=auth_url,
                 strategy=force_strategy or auth_strategy,
                 region=region)

    if creds['strategy'] == 'keystone' and not creds['auth_url']:
        msg = ("--auth_url option or OS_AUTH_URL environment variable "
               "required when keystone authentication strategy is enabled\n")
        raise exception.ClientConfigurationError(msg)

    use_ssl = (creds['auth_url'] is not None and
               creds['auth_url'].find('https') != -1)

    client = HeatClient

    return client(host=host,
                  port=port,
                  use_ssl=use_ssl,
                  auth_tok=auth_token,
                  creds=creds,
                  insecure=insecure,
                  service_type='cloudformation')
