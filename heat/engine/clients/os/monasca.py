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

from monascaclient import exc as monasca_exc
from monascaclient.v2_0 import client as monasca_client

from heat.common import exception as heat_exc
from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'monasca'


class MonascaClientPlugin(client_plugin.ClientPlugin):
    exceptions_module = [monasca_exc]

    service_types = [MONITORING] = ['monitoring']

    VERSION = '2_0'

    def _create(self):
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        endpoint = self.url_for(service_type=self.MONITORING,
                                endpoint_type=interface)

        # Directly use v2_0 client to avoid dynamic import in monasca client,
        # We can switch back once https://review.opendev.org/#/c/700989 fixed.
        return monasca_client.Client(
            session=self.context.keystone_session,
            service_type='monitoring',
            endpoint=endpoint)

    def is_not_found(self, ex):
        return isinstance(ex, monasca_exc.NotFound)

    def is_un_processable(self, ex):
        return isinstance(ex, monasca_exc.UnprocessableEntity)

    def get_notification(self, notification):
        try:
            return self.client().notifications.get(
                notification_id=notification)['id']
        except monasca_exc.NotFound:
            raise heat_exc.EntityNotFound(entity='Monasca Notification',
                                          name=notification)


class MonascaNotificationConstraint(constraints.BaseCustomConstraint):

    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_notification'
