# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Simple client class to speak with any RESTful service that implements
the heat Engine API
"""

import json
import logging

from heat.common.client import BaseClient
from heat.common import crypt
from heat.common import config
from heat.openstack.common import cfg

from heat.cloudformations import *

logger = logging.getLogger(__name__)

_CLIENT_CREDS = None
_CLIENT_HOST = None
_CLIENT_PORT = None
_CLIENT_KWARGS = {}
# AES key used to encrypt 'location' metadata
_METADATA_ENCRYPTION_KEY = None


engine_addr_opts = [
    cfg.StrOpt('engine_host', default='0.0.0.0'),
    cfg.IntOpt('engine_port', default=8001),
    ]
engine_client_opts = [
    cfg.StrOpt('engine_client_protocol', default='http'),
    cfg.StrOpt('engine_client_key_file'),
    cfg.StrOpt('engine_client_cert_file'),
    cfg.StrOpt('engine_client_ca_file'),
    cfg.StrOpt('metadata_encryption_key'),
    ]

class EngineClient(BaseClient):

    """A client for the Engine stack metadata service"""

    DEFAULT_PORT = 8001

    def __init__(self, host=None, port=None, metadata_encryption_key=None,
                 **kwargs):
        """
        :param metadata_encryption_key: Key used to encrypt 'location' metadata
        """
        self.metadata_encryption_key = metadata_encryption_key
        # NOTE (dprince): by default base client overwrites host and port
        # settings when using keystone. configure_via_auth=False disables
        # this behaviour to ensure we still send requests to the Engine API
        BaseClient.__init__(self, host, port, configure_via_auth=False,
                            **kwargs)

    def get_stacks(self, **kwargs):
        """
        Returns a list of stack id/name mappings from Engine

        :param filters: dict of keys & expected values to filter results
        :param marker: stack id after which to start page
        :param limit: max number of stacks to return
        :param sort_key: results will be ordered by this stack attribute
        :param sort_dir: direction in which to to order results (asc, desc)
        """
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        res = self.do_request("GET", "/stacks", params=params)
        return json.loads(res.read())['stacks']

    def show_stack(self, stack_id):
        """Returns a mapping of stack metadata from Engine"""
        res = self.do_request("GET", "/stacks/%s" % stack_id)
        data = json.loads(res.read())['stacks']
        return data

    def validate_template(self, template, **kwargs):
        """
        Validate the template
        """
        logger.info(template)
        res = self.do_request("POST", "/validate_template", template,
                              params=kwargs)
        data = json.loads(res.read())
        logger.info(data)
        return data

    def create_stack(self, template, **kwargs):
        """
        Tells engine about an stack's metadata
        """
        res = self.do_request("POST", "/stacks", template, params=kwargs)
        data = json.loads(res.read())
        return data

    def update_stack(self, stack_id, template):
        """
        Updates Engine's information about an stack
        """
        res = self.do_request("PUT", "/stacks/%s" % (stack_id), template)
        data = json.loads(res.read())
        stack = data['stack']
        return stack

    def delete_stack(self, stack_id):
        """
        Deletes Engine's information about an stack
        """
        res = self.do_request("DELETE", "/stacks/%s" % stack_id)
        return res

    def get_stack_events(self, **kwargs):
        params = self._extract_params(kwargs, SUPPORTED_PARAMS)
        res = self.do_request("GET", "/stacks/%s/events" % (params['StackName']),
                              params=params)
        return json.loads(res.read())['events']

def get_engine_addr(conf):
    conf.register_opts(engine_addr_opts)
    return (conf.engine_host, conf.engine_port)


def configure_engine_client(conf):
    """
    Sets up a engine client for use in engine lookups

    :param conf: Configuration options coming from controller
    """
    global _CLIENT_KWARGS, _CLIENT_HOST, _CLIENT_PORT, _METADATA_ENCRYPTION_KEY
    try:
        host, port = get_engine_addr(conf)
    except cfg.ConfigFileValueError:
        msg = _("Configuration option was not valid")
        logger.error(msg)
        raise exception.BadEngineConnectionConfiguration(msg)
    except IndexError:
        msg = _("Could not find required configuration option")
        logger.error(msg)
        raise exception.BadEngineConnectionConfiguration(msg)

    conf.register_opts(engine_client_opts)

    _CLIENT_HOST = host
    _CLIENT_PORT = port
    _METADATA_ENCRYPTION_KEY = conf.metadata_encryption_key
    _CLIENT_KWARGS = {
        'use_ssl': conf.engine_client_protocol.lower() == 'https',
        'key_file': conf.engine_client_key_file,
        'cert_file': conf.engine_client_cert_file,
        'ca_file': conf.engine_client_ca_file
        }



def get_engine_client(cxt):
    global _CLIENT_CREDS, _CLIENT_KWARGS, _CLIENT_HOST, _CLIENT_PORT
    global _METADATA_ENCRYPTION_KEY
    kwargs = _CLIENT_KWARGS.copy()
    kwargs['auth_tok'] = cxt.auth_tok
    if _CLIENT_CREDS:
        kwargs['creds'] = _CLIENT_CREDS
    return EngineClient(_CLIENT_HOST, _CLIENT_PORT,
                        _METADATA_ENCRYPTION_KEY, **kwargs)


