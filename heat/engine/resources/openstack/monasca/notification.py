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

    NOTIFICATION_TYPES = (
        EMAIL, WEBHOOK, PAGERDUTY
    ) = (
        'email', 'webhook', 'pagerduty'
    )

    PROPERTIES = (
        NAME, TYPE, ADDRESS
    ) = (
        'name', 'type', 'address'
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
        )
    }

    def handle_create(self):
        args = dict(
            name=(self.properties[self.NAME] or
                  self.physical_resource_name()),
            type=self.properties[self.TYPE],
            address=self.properties[self.ADDRESS]
        )

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

        self.client().notifications.update(**args)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().notifications.delete(
                    notification_id=self.resource_id)

    # FIXME(kanagaraj-manickam) Remove this method once monasca defect 1484900
    # is fixed.
    def _show_resource(self):
        return self.client().notifications.get(self.resource_id)


def resource_mapping():
    return {
        'OS::Monasca::Notification': MonascaNotification
    }
