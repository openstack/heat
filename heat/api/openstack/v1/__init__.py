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

import json
import urlparse
import httplib
import routes
import gettext

gettext.install('heat', unicode=1)

from heat.api.openstack.v1 import stacks
from heat.common import wsgi

from webob import Request
import webob
from heat import utils
from heat.common import context

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class API(wsgi.Router):

    """
    WSGI router for Heat v1 ReST API requests.
    """

    def __init__(self, conf, **local_conf):
        self.conf = conf
        mapper = routes.Mapper()

        stacks_resource = stacks.create_resource(conf)

        # Stack collection
        mapper.connect("stack", "/{tenant_id}/stacks",
                       controller=stacks_resource, action="index",
                       conditions={'method': 'GET'})
        mapper.connect("stack", "/{tenant_id}/stacks",
                       controller=stacks_resource, action="create",
                       conditions={'method': 'POST'})

        # Stack data
        mapper.connect("stack", "/{tenant_id}/stacks/{stack_name}",
                       controller=stacks_resource, action="lookup")
        mapper.connect("stack", "/{tenant_id}/stacks/{stack_name}/{stack_id}",
                       controller=stacks_resource, action="show",
                       conditions={'method': 'GET'})
        mapper.connect("stack",
                       "/{tenant_id}/stacks/{stack_name}/{stack_id}/template",
                       controller=stacks_resource, action="template",
                       conditions={'method': 'GET'})

        # Stack update/delete
        mapper.connect("stack", "/{tenant_id}/stacks/{stack_name}/{stack_id}",
                       controller=stacks_resource, action="update",
                       conditions={'method': 'PUT'})
        mapper.connect("stack", "/{tenant_id}/stacks/{stack_name}/{stack_id}",
                       controller=stacks_resource, action="delete",
                       conditions={'method': 'DELETE'})

        # Template handling
        mapper.connect("stack", "/{tenant_id}/validate",
                       controller=stacks_resource, action="validate_template",
                       conditions={'method': 'POST'})

        super(API, self).__init__(mapper)
