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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

from oslo_serialization import jsonutils


class ZaqarSubscription(resource.Resource):
    """A resource for managing Zaqar subscriptions.

    A Zaqar subscription listens for messages in a queue and sends a
    notification over email or webhook.
    """

    default_client_name = "zaqar"

    support_status = support.SupportStatus(version='8.0.0',
                                           status=support.SUPPORTED)

    PROPERTIES = (
        QUEUE_NAME, SUBSCRIBER, TTL, OPTIONS,
    ) = (
        'queue_name', 'subscriber', 'ttl', 'options',
    )

    properties_schema = {
        QUEUE_NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name of the queue to subscribe to."),
            constraints=[constraints.CustomConstraint('zaqar.queue')],
            required=True),
        SUBSCRIBER: properties.Schema(
            properties.Schema.STRING,
            _("URI of the subscriber which will be notified. Must be in the "
              "format: <TYPE>:<VALUE>."),
            required=True,
            update_allowed=True),
        TTL: properties.Schema(
            properties.Schema.INTEGER,
            _("Time to live of the subscription in seconds."),
            update_allowed=True,
            default=220367260800,  # Seconds until the year 9000
                                   # (ie. never expire)
            constraints=[
                constraints.Range(
                    min=60,
                ),
            ],
        ),
        OPTIONS: properties.Schema(
            properties.Schema.MAP,
            _("Options used to configure this subscription."),
            required=False,
            update_allowed=True)
    }

    VALID_SUBSCRIBER_TYPES = ['http', 'https', 'mailto', 'trust+http',
                              'trust+https']

    def validate(self):
        super(ZaqarSubscription, self).validate()
        self._validate_subscriber()

    def _validate_subscriber(self):
        subscriber_type = self.properties[self.SUBSCRIBER].split(":", 1)[0]
        if subscriber_type not in self.VALID_SUBSCRIBER_TYPES:
            msg = (_("The subscriber type of must be one of: %s.")
                   % ", ".join(self.VALID_SUBSCRIBER_TYPES))
            raise exception.StackValidationFailed(message=msg)

    def _subscriber_url(self):
        return self.properties[self.SUBSCRIBER]

    def _subscription_options(self):
        return self.properties[self.OPTIONS]

    def _subscription_data(self):
        return {
            'subscriber': self._subscriber_url(),
            'ttl': self.properties[self.TTL],
            'options': self._subscription_options(),
        }

    def handle_create(self):
        """Create a subscription to a Zaqar message queue."""
        subscription = self.client().subscription(
            self.properties[self.QUEUE_NAME],
            **self._subscription_data())
        self.resource_id_set(subscription.id)

    def _get_subscription(self):
        return self.client().subscription(
            self.properties[self.QUEUE_NAME],
            id=self.resource_id,
            auto_create=False
        )

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        """Update a subscription to a Zaqar message queue."""
        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)
        subscription = self._get_subscription()
        subscription.update(self._subscription_data())

    def handle_delete(self):
        if self.resource_id is None:
            return
        with self.client_plugin().ignore_not_found:
            self._get_subscription().delete()

    def _show_resource(self):
        subscription = self._get_subscription()
        return vars(subscription)

    def parse_live_resource_data(self, resource_properties, resource_data):
        return {
            self.QUEUE_NAME: resource_data[self.QUEUE_NAME],
            self.SUBSCRIBER: resource_data[self.SUBSCRIBER],
            self.TTL: resource_data[self.TTL],
            self.OPTIONS: resource_data[self.OPTIONS]
        }


class MistralTrigger(ZaqarSubscription):
    """A Zaqar subscription for triggering Mistral workflows.

    This Zaqar subscription type listens for messages in a queue and triggers a
    Mistral workflow execution each time one is received.

    The content of the Zaqar message is passed to the workflow in the
    environment with the name "notification", and thus is accessible from
    within the workflow as:

        <% env().notification %>

    Other environment variables can be set using the 'env' key in the params
    property.
    """

    support_status = support.SupportStatus(version='8.0.0',
                                           status=support.SUPPORTED)

    PROPERTIES = (
        QUEUE_NAME, TTL,
        WORKFLOW_ID, PARAMS, INPUT,
    ) = (
        ZaqarSubscription.QUEUE_NAME, ZaqarSubscription.TTL,
        'workflow_id', 'params', 'input',
    )

    properties_schema = {
        QUEUE_NAME: ZaqarSubscription.properties_schema[QUEUE_NAME],
        TTL: ZaqarSubscription.properties_schema[TTL],
        WORKFLOW_ID: properties.Schema(
            properties.Schema.STRING,
            _("UUID of the Mistral workflow to trigger."),
            required=True,
            constraints=[constraints.CustomConstraint('mistral.workflow')],
            update_allowed=True),
        PARAMS: properties.Schema(
            properties.Schema.MAP,
            _("Parameters to pass to the Mistral workflow execution. "
              "The parameters depend on the workflow type."),
            required=False,
            default={},
            update_allowed=True),
        INPUT: properties.Schema(
            properties.Schema.MAP,
            _("Input values to pass to the Mistral workflow."),
            required=False,
            default={},
            update_allowed=True),
    }

    def _validate_subscriber(self):
        pass

    def _subscriber_url(self):
        mistral_client = self.client('mistral')
        manager = getattr(mistral_client.executions, 'client',
                          mistral_client.executions)
        return 'trust+%s/executions' % manager.http_client.base_url

    def _subscription_options(self):
        params = dict(self.properties[self.PARAMS])
        params.setdefault('env', {})
        params['env']['notification'] = "$zaqar_message$"
        post_data = {
            self.WORKFLOW_ID: self.properties[self.WORKFLOW_ID],
            self.PARAMS: params,
            self.INPUT: self.properties[self.INPUT],
        }
        return {
            'post_data': jsonutils.dumps(post_data)
        }

    def parse_live_resource_data(self, resource_properties, resource_data):
        options = resource_data.get(self.OPTIONS, {})
        post_data = jsonutils.loads(options.get('post_data', '{}'))
        params = post_data.get(self.PARAMS, {})
        env = params.get('env', {})
        env.pop('notification', None)
        if not env:
            params.pop('env', None)

        return {
            self.QUEUE_NAME: resource_data.get(self.QUEUE_NAME),
            self.TTL: resource_data.get(self.TTL),
            self.WORKFLOW_ID: post_data.get(self.WORKFLOW_ID),
            self.PARAMS: params,
            self.INPUT: post_data.get(self.INPUT),
        }


def resource_mapping():
    return {
        'OS::Zaqar::Subscription': ZaqarSubscription,
        'OS::Zaqar::MistralTrigger': MistralTrigger,
    }
