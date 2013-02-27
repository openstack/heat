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
Client implementation based on the boto AWS client library
"""

from heat.openstack.common import log as logging
logger = logging.getLogger(__name__)

from boto.ec2.cloudwatch import CloudWatchConnection


class BotoCWClient(CloudWatchConnection):
    '''
    Wrapper class for boto CloudWatchConnection class
    '''
    # TODO : These should probably go in the CW API and be imported
    DEFAULT_NAMESPACE = "heat/unknown"
    METRIC_UNITS = ("Seconds", "Microseconds", "Milliseconds", "Bytes",
                    "Kilobytes", "Megabytes", "Gigabytes", "Terabytes",
                    "Bits", "Kilobits", "Megabits", "Gigabits", "Terabits",
                    "Percent", "Count", "Bytes/Second", "Kilobytes/Second",
                    "Megabytes/Second", "Gigabytes/Second", "Terabytes/Second",
                    "Bits/Second", "Kilobits/Second", "Megabits/Second",
                    "Gigabits/Second", "Terabits/Second", "Count/Second", None)
    METRIC_COMPARISONS = (">=", ">", "<", "<=")
    ALARM_STATES = ("OK", "ALARM", "INSUFFICIENT_DATA")
    METRIC_STATISTICS = ("Average", "Sum", "SampleCount", "Maximum", "Minimum")

    # Note, several of these boto calls take a list of alarm names, so
    # we could easily handle multiple alarms per-action, but in the
    # interests of keeping the client simple, we just handle one 'AlarmName'

    def describe_alarm(self, **kwargs):
        # If no AlarmName specified, we pass None, which returns
        # results for ALL alarms
        try:
            name = kwargs['AlarmName']
        except KeyError:
            name = None
        return super(BotoCWClient, self).describe_alarms(
            alarm_names=[name])

    def list_metrics(self, **kwargs):
        # list_metrics returns non-null index in next_token if there
        # are more than 500 metric results, in which case we have to
        # re-read with the token to get the next batch of results
        #
        # Also note that we can do more advanced filtering by dimension
        # and/or namespace, but for simplicity we only filter by
        # MetricName for the time being
        try:
            name = kwargs['MetricName']
        except KeyError:
            name = None

        results = []
        token = None
        while True:
            results.append(super(BotoCWClient, self).list_metrics(
                           next_token=token,
                           dimensions=None,
                           metric_name=name,
                           namespace=None))
            if not token:
                break

        return results

    def put_metric_data(self, **kwargs):
        '''
        Publish metric data points to CloudWatch
        '''
        try:
            metric_name = kwargs['MetricName']
            metric_unit = kwargs['MetricUnit']
            metric_value = kwargs['MetricValue']
            metric_namespace = kwargs['Namespace']
        except KeyError:
            logger.error("Must pass MetricName, MetricUnit, " +
                         "Namespace, MetricValue!")
            return

        try:
            metric_unit = kwargs['MetricUnit']
        except KeyError:
            metric_unit = None

        # If we're passed AlarmName, we attach it to the metric
        # as a dimension
        try:
            metric_dims = [{'AlarmName': kwargs['AlarmName']}]
        except KeyError:
            metric_dims = []

        if metric_unit not in self.METRIC_UNITS:
            logger.error("MetricUnit not an allowed value")
            logger.error("MetricUnit must be one of %s" % self.METRIC_UNITS)
            return

        return super(BotoCWClient, self).put_metric_data(
            namespace=metric_namespace,
            name=metric_name,
            value=metric_value,
            timestamp=None,  # This means use "now" in the engine
            unit=metric_unit,
            dimensions=metric_dims,
            statistics=None)

    def set_alarm_state(self, **kwargs):
        return super(BotoCWClient, self).set_alarm_state(
            alarm_name=kwargs['AlarmName'],
            state_reason=kwargs['StateReason'],
            state_value=kwargs['StateValue'],
            state_reason_data=kwargs['StateReasonData'])

    def format_metric_alarm(self, alarms):
        '''
        Return string formatted representation of
        boto.ec2.cloudwatch.alarm.MetricAlarm objects
        '''
        ret = []
        for s in alarms:
            ret.append("AlarmName : %s" % s.name)
            ret.append("AlarmDescription : %s" % s.description)
            ret.append("ActionsEnabled : %s" % s.actions_enabled)
            ret.append("AlarmActions : %s" % s.alarm_actions)
            ret.append("AlarmArn : %s" % s.alarm_arn)
            ret.append("AlarmConfigurationUpdatedTimestamp : %s" %
                       s.last_updated)
            ret.append("ComparisonOperator : %s" % s.comparison)
            ret.append("Dimensions : %s" % s.dimensions)
            ret.append("EvaluationPeriods : %s" % s.evaluation_periods)
            ret.append("InsufficientDataActions : %s" %
                       s.insufficient_data_actions)
            ret.append("MetricName : %s" % s.metric)
            ret.append("Namespace : %s" % s.namespace)
            ret.append("OKActions : %s" % s.ok_actions)
            ret.append("Period : %s" % s.period)
            ret.append("StateReason : %s" % s.state_reason)
            ret.append("StateUpdatedTimestamp : %s" %
                       s.last_updated)
            ret.append("StateValue : %s" % s.state_value)
            ret.append("Statistic : %s" % s.statistic)
            ret.append("Threshold : %s" % s.threshold)
            ret.append("Unit : %s" % s.unit)
            ret.append("--")
        return '\n'.join(ret)

    def format_metric(self, metrics):
        '''
        Return string formatted representation of
        boto.ec2.cloudwatch.metric.Metric objects
        '''
        # Boto appears to return metrics as a list-inside-a-list
        # probably a bug in boto, but work around here
        if len(metrics) == 1:
            metlist = metrics[0]
        elif len(metrics) == 0:
            metlist = []
        else:
            # Shouldn't get here, unless boto gets fixed..
            logger.error("Unexpected metric list-of-list length (boto fixed?)")
            return "ERROR\n--"

        ret = []
        for m in metlist:
                ret.append("MetricName : %s" % m.name)
                ret.append("Namespace  : %s" % m.namespace)
                ret.append("Dimensions : %s" % m.dimensions)
                ret.append("--")
        return '\n'.join(ret)


def get_client(port=None, aws_access_key=None, aws_secret_key=None):
    """
    Returns a new boto CloudWatch client connection to a heat server
    Note : Configuration goes in /etc/boto.cfg, not via arguments
    """

    # Note we pass None/None for the keys so boto reads /etc/boto.cfg
    # Also note is_secure is defaulted to False as HTTPS connections
    # don't seem to work atm, FIXME
    cloudwatch = BotoCWClient(aws_access_key_id=aws_access_key,
                              aws_secret_access_key=aws_secret_key,
                              is_secure=False,
                              port=port,
                              path="/v1")
    if cloudwatch:
        logger.debug("Got CW connection object OK")
    else:
        logger.error("Error establishing CloudWatch connection!")
        sys.exit(1)

    return cloudwatch
