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

from functools import partial
import logging
import routes

from heat.api.v1 import stacks
from heat.common import wsgi

from webob import Request

logger = logging.getLogger(__name__)


class API(wsgi.Router):

    """
    WSGI router for Heat v1 API requests.
    """

    def action_match(self, action, environ, result):
        req = Request(environ)
        env_action = req.GET.get("Action")
        return action == env_action

    def action(self, name):
        """
        Return a function that matches a request's `Action` query parameter to
        the given value.
        """
        return partial(self.action_match, name)

    def __init__(self, conf, **local_conf):
        self.conf = conf
        mapper = routes.Mapper()

        stacks_resource = stacks.create_resource(conf)

        mapper.resource("stack", "stacks", controller=stacks_resource,
            collection={'detail': 'GET'})

        mapper.connect("/", controller=stacks_resource,
            action="list", conditions=dict(function=self.action('ListStacks')))

        mapper.connect("/", controller=stacks_resource,
            action="create",
            conditions=dict(function=self.action('CreateStack')))

        mapper.connect("/", controller=stacks_resource,
            action="describe",
            conditions=dict(function=self.action('DescribeStacks')))

        mapper.connect("/", controller=stacks_resource,
            action="delete",
            conditions=dict(function=self.action('DeleteStack')))

        mapper.connect("/", controller=stacks_resource,
            action="update",
            conditions=dict(function=self.action('UpdateStack')))

        mapper.connect("/", controller=stacks_resource,
            action="events_list",
            conditions=dict(function=self.action('DescribeStackEvents')))

        mapper.connect("/", controller=stacks_resource,
                       action="validate_template",
                       conditions=dict(function=self.action('ValidateTemplate')))

        mapper.connect("/", controller=stacks_resource, action="index")

        super(API, self).__init__(mapper)
