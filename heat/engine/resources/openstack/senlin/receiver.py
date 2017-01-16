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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.senlin import res_base


class Receiver(res_base.BaseSenlinResource):
    """A resource that creates Senlin Receiver.

    Receiver is an abstract resource created at the senlin engine
    that can be used to hook the engine to some external event/alarm sources.
    """

    entity = 'receiver'

    PROPERTIES = (
        CLUSTER, ACTION, NAME, TYPE, PARAMS,
    ) = (
        'cluster', 'action', 'name', 'type', 'params',
    )

    ATTRIBUTES = (
        ATTR_CHANNEL,
    ) = (
        'channel',
    )

    _ACTIONS = (
        CLUSTER_SCALE_OUT, CLUSTER_SCALE_IN,
    ) = (
        'CLUSTER_SCALE_OUT', 'CLUSTER_SCALE_IN',
    )

    _TYPES = (
        WEBHOOK,
    ) = (
        'webhook',
    )

    properties_schema = {
        CLUSTER: properties.Schema(
            properties.Schema.STRING,
            _('Name or ID of target cluster.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('senlin.cluster')
            ]
        ),
        ACTION: properties.Schema(
            properties.Schema.STRING,
            _('The action to be executed when the receiver is signaled.'),
            required=True,
            constraints=[
                constraints.AllowedValues(_ACTIONS)
            ]
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the senlin receiver. By default, '
              'physical resource name is used.'),
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Type of receiver.'),
            default=WEBHOOK,
            constraints=[
                constraints.AllowedValues(_TYPES)
            ]
        ),
        PARAMS: properties.Schema(
            properties.Schema.MAP,
            _('The parameters passed to action when the receiver '
              'is signaled.'),
        ),
    }

    attributes_schema = {
        ATTR_CHANNEL: attributes.Schema(
            _("The channel for receiving signals."),
            type=attributes.Schema.MAP
        ),
    }

    def handle_create(self):
        params = {
            'name': (self.properties[self.NAME] or
                     self.physical_resource_name()),
            'cluster_id': self.properties[self.CLUSTER],
            'type': self.properties[self.TYPE],
            'action': self.properties[self.ACTION],
            'params': self.properties[self.PARAMS],
        }

        recv = self.client().create_receiver(**params)
        self.resource_id_set(recv.id)

    def handle_delete(self):
        if self.resource_id is not None:
            with self.client_plugin().ignore_not_found:
                self.client().delete_receiver(self.resource_id)


def resource_mapping():
    return {
        'OS::Senlin::Receiver': Receiver
    }
