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

import re
from six.moves import urllib

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class MonascaNotification(resource.Resource):
    """Heat Template Resource for Monasca Notification.

    A resource which is used to notificate if there is some alarm.
    Monasca Notification helps to declare the hook points, which will be
    invoked once alarm is generated. This plugin helps to create, update and
    delete the notification.
    """

    support_status = support.SupportStatus(
        version='7.0.0',
        previous_status=support.SupportStatus(
            version='5.0.0',
            status=support.UNSUPPORTED
        ))

    default_client_name = 'monasca'

    entity = 'notifications'

    # NOTE(sirushti): To conform to the autoscaling behaviour in heat, we set
    # the default period interval during create/update to 60 for webhooks only.
    _default_period_interval = 60

    NOTIFICATION_TYPES = (
        EMAIL, WEBHOOK, PAGERDUTY
    ) = (
        'email', 'webhook', 'pagerduty'
    )

    PROPERTIES = (
        NAME, TYPE, ADDRESS, PERIOD
    ) = (
        'name', 'type', 'address', 'period'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the notification. By default, physical resource name '
              'is used.'),
            update_allowed=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of the notification.'),
            update_allowed=True,
            required=True,
            constraints=[constraints.AllowedValues(
                NOTIFICATION_TYPES
            )]
        ),
        ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _('Address of the notification. It could be a valid email '
              'address, url or service key based on notification type.'),
            update_allowed=True,
            required=True,
            constraints=[constraints.Length(max=512)]
        ),
        PERIOD: properties.Schema(
            properties.Schema.INTEGER,
            _('Interval in seconds to invoke webhooks if the alarm state '
              'does not transition away from the defined trigger state. A '
              'value of 0 will disable continuous notifications. This '
              'property is only applicable for the webhook notification '
              'type and has default period interval of 60 seconds.'),
            support_status=support.SupportStatus(version='7.0.0'),
            update_allowed=True,
            constraints=[constraints.AllowedValues([0, 60])]
        )
    }

    def _period_interval(self):
        period = self.properties[self.PERIOD]
        if period is None:
            period = self._default_period_interval
        return period

    def validate(self):
        super(MonascaNotification, self).validate()
        if self.properties[self.PERIOD] is not None and (
                self.properties[self.TYPE] != self.WEBHOOK):
            msg = _('The period property can only be specified against a '
                    'Webhook Notification type.')
            raise exception.StackValidationFailed(message=msg)

        address = self.properties[self.ADDRESS]
        if not address:
            return

        if self.properties[self.TYPE] == self.WEBHOOK:
            try:
                parsed_address = urllib.parse.urlparse(address)
            except Exception:
                msg = _('Address "%(addr)s" should have correct format '
                        'required by "%(wh)s" type of "%(type)s" '
                        'property') % {
                    'addr': address,
                    'wh': self.WEBHOOK,
                    'type': self.TYPE}
                raise exception.StackValidationFailed(message=msg)
            if not parsed_address.scheme:
                msg = _('Address "%s" doesn\'t have required URL '
                        'scheme') % address
                raise exception.StackValidationFailed(message=msg)
            if not parsed_address.netloc:
                msg = _('Address "%s" doesn\'t have required network '
                        'location') % address
                raise exception.StackValidationFailed(message=msg)
            if parsed_address.scheme not in ['http', 'https']:
                msg = _('Address "%(addr)s" doesn\'t satisfies '
                        'allowed schemes: %(schemes)s') % {
                    'addr': address,
                    'schemes': ', '.join(['http', 'https'])
                }
                raise exception.StackValidationFailed(message=msg)
        elif (self.properties[self.TYPE] == self.EMAIL and
              not re.match(r'^\S+@\S+$', address)):
            msg = _('Address "%(addr)s" doesn\'t satisfies allowed format for '
                    '"%(email)s" type of "%(type)s" property') % {
                'addr': address,
                'email': self.EMAIL,
                'type': self.TYPE}
            raise exception.StackValidationFailed(message=msg)

    def handle_create(self):
        args = dict(
            name=(self.properties[self.NAME] or
                  self.physical_resource_name()),
            type=self.properties[self.TYPE],
            address=self.properties[self.ADDRESS],
        )
        if args['type'] == self.WEBHOOK:
            args['period'] = self._period_interval()

        notification = self.client().notifications.create(**args)
        self.resource_id_set(notification['id'])

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        args = dict(notification_id=self.resource_id)

        args['name'] = (prop_diff.get(self.NAME) or
                        self.properties[self.NAME])

        args['type'] = (prop_diff.get(self.TYPE) or
                        self.properties[self.TYPE])

        args['address'] = (prop_diff.get(self.ADDRESS) or
                           self.properties[self.ADDRESS])

        if args['type'] == self.WEBHOOK:
            updated_period = prop_diff.get(self.PERIOD)
            args['period'] = (updated_period if updated_period is not None
                              else self._period_interval())

        self.client().notifications.update(**args)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().notifications.delete(
                    notification_id=self.resource_id)


def resource_mapping():
    return {
        'OS::Monasca::Notification': MonascaNotification
    }
