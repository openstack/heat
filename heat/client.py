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

import json
import logging
import os
from heat.common import client as base_client
from heat.common import exception
from heat.cloudformations import *
logger = logging.getLogger(__name__)


class V1Client(base_client.BaseClient):

    """Main client class for accessing heat resources"""

    DEFAULT_DOC_ROOT = "/v1"

    def _insert_common_parameters(self, params):
        params['Version'] = '2010-05-15'
        params['SignatureVersion'] = '2'
        params['SignatureMethod'] = 'HmacSHA256'
        params['KeyStoneCreds'] = self.creds

    def list_stacks(self, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)

        res = self.do_request("GET", "/ListStacks", params=params)
        data = json.loads(res.read())
        return data

    def describe_stacks(self, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)

        res = self.do_request("GET", "/DescribeStacks", params=params)
        data = json.loads(res.read())
        return data

    def create_stack(self, **kwargs):

        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)
        res = self.do_request("POST", "/CreateStack", params=params)
        data = json.loads(res.read())
        return data

    def update_stack(self, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)
        res = self.do_request("PUT", "/UpdateStack", params=params)

        data = json.loads(res.read())
        return data

    def delete_stack(self, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)
        res = self.do_request("DELETE", "/DeleteStack", params=params)
        data = json.loads(res.read())
        return data

    def list_stack_events(self, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)

        res = self.do_request("GET", "/DescribeStackEvents", params=params)
        data = json.loads(res.read())
        return data

    def validate_template(self, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        self._insert_common_parameters(params)
        
        res = self.do_request("GET", "/ValidateTemplate", params=params)
        data = json.loads(res.read())
        return data

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
                 region=region,
    )

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
                insecure=insecure)
