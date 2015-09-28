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

import routes
import webob

from heat.api.cfn.v1 import signal
from heat.api.cfn.v1 import stacks
from heat.common import wsgi


class API(wsgi.Router):

    """WSGI router for Heat CloudFormation v1 API requests."""

    _actions = {
        'list': 'ListStacks',
        'create': 'CreateStack',
        'describe': 'DescribeStacks',
        'delete': 'DeleteStack',
        'update': 'UpdateStack',
        'cancel_update': 'CancelUpdateStack',
        'events_list': 'DescribeStackEvents',
        'validate_template': 'ValidateTemplate',
        'get_template': 'GetTemplate',
        'estimate_template_cost': 'EstimateTemplateCost',
        'describe_stack_resource': 'DescribeStackResource',
        'describe_stack_resources': 'DescribeStackResources',
        'list_stack_resources': 'ListStackResources',
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
                req = webob.Request(environ)
                env_action = req.params.get("Action")
                return env_action == api_action

            return {'function': action_match}

        for action in self._actions:
            mapper.connect("/", controller=stacks_resource, action=action,
                           conditions=conditions(action))

        mapper.connect("/", controller=stacks_resource, action="index")

        # Add controller which handles signals on resources like:
        # waitconditions and alarms.
        # This is not part of the main CFN API spec, hence handle it
        # separately via a different path
        signal_controller = signal.create_resource(conf)
        mapper.connect('/waitcondition/{arn:.*}',
                       controller=signal_controller,
                       action='update_waitcondition',
                       conditions=dict(method=['PUT']))
        mapper.connect('/signal/{arn:.*}',
                       controller=signal_controller,
                       action='signal',
                       conditions=dict(method=['POST']))

        super(API, self).__init__(mapper)
