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

import logging
import routes
import gettext

gettext.install('heat', unicode=1)

from heat.api.v1 import stacks
from heat.common import wsgi

from webob import Request

logger = logging.getLogger(__name__)


class API(wsgi.Router):

    """
    WSGI router for Heat v1 API requests.
    """

    _actions = {
        'list': 'ListStacks',
        'create': 'CreateStack',
        'describe': 'DescribeStacks',
        'delete': 'DeleteStack',
        'update': 'UpdateStack',
        'events_list': 'DescribeStackEvents',
        'validate_template': 'ValidateTemplate',
    }

    def __init__(self, conf, **local_conf):
        self.conf = conf
        mapper = routes.Mapper()

        stacks_resource = stacks.create_resource(conf)

        mapper.resource("stack", "stacks", controller=stacks_resource,
                        collection={'detail': 'GET'})

        def conditions(action):
            api_action = self._actions[action]

            def action_match(environ, result):
                req = Request(environ)
                env_action = req.GET.get("Action")
                return env_action == api_action

            return {'function': action_match}

        for action in self._actions:
            mapper.connect("/", controller=stacks_resource, action=action,
                conditions=conditions(action))

        mapper.connect("/", controller=stacks_resource, action="index")

        super(API, self).__init__(mapper)
