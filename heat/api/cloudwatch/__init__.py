
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
from webob import Request

from heat.api.cloudwatch import versions
from heat.api.cloudwatch import watch
from heat.api.middleware.version_negotiation import VersionNegotiationFilter
from heat.common import wsgi
from heat.openstack.common import gettextutils
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)
gettextutils.install('heat')


class API(wsgi.Router):

    """
    WSGI router for Heat CloudWatch API
    """

    _actions = {
        'delete_alarms': 'DeleteAlarms',
        'describe_alarm_history': 'DescribeAlarmHistory',
        'describe_alarms': 'DescribeAlarms',
        'describe_alarms_for_metric': 'DescribeAlarmsForMetric',
        'disable_alarm_actions': 'DisableAlarmActions',
        'enable_alarm_actions': 'EnableAlarmActions',
        'get_metric_statistics': 'GetMetricStatistics',
        'list_metrics': 'ListMetrics',
        'put_metric_alarm': 'PutMetricAlarm',
        'put_metric_data': 'PutMetricData',
        'set_alarm_state': 'SetAlarmState',
    }

    def __init__(self, conf, **local_conf):
        self.conf = conf
        mapper = routes.Mapper()
        controller_resource = watch.create_resource(conf)

        def conditions(action):
            api_action = self._actions[action]

            def action_match(environ, result):
                req = Request(environ)
                env_action = req.params.get("Action")
                return env_action == api_action

            return {'function': action_match}

        for action in self._actions:
            mapper.connect("/", controller=controller_resource, action=action,
                           conditions=conditions(action))

        mapper.connect("/", controller=controller_resource, action="index")

        super(API, self).__init__(mapper)


def version_negotiation_filter(app, conf, **local_conf):
    return VersionNegotiationFilter(versions.Controller, app,
                                    conf, **local_conf)
