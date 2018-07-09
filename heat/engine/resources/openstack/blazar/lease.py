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
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support


class Lease(resource.Resource):
    """A resource to manage Blazar leases.

    Lease resource manages the reservations of specific type/amount of
    cloud resources within OpenStack.

    Note:
    Based on an agreement with Blazar team, this resource class does not
    support updating, because current Blazar lease scheme is not suitable for
    Heat, if you want to update a lease, you need to specify reservation's id,
    which is one of attribute of lease.
    """

    support_status = support.SupportStatus(version='12.0.0')

    PROPERTIES = (
        NAME, START_DATE, END_DATE, BEFORE_END_DATE,
        RESERVATIONS, RESOURCE_TYPE, MIN, MAX,
        HYPERVISOR_PROPERTIES, RESOURCE_PROPERTIES, BEFORE_END,
        AMOUNT, VCPUS, MEMORY_MB, DISK_GB, AFFINITY, EVENTS,
        EVENT_TYPE, TIME,
    ) = (
        'name', 'start_date', 'end_date', 'before_end_date',
        'reservations', 'resource_type', 'min', 'max',
        'hypervisor_properties', 'resource_properties', 'before_end',
        'amount', 'vcpus', 'memory_mb', 'disk_gb', 'affinity', 'events',
        'event_type', 'time',
    )

    ATTRIBUTES = (
        NAME_ATTR, START_DATE_ATTR, END_DATE_ATTR, CREATED_AT_ATTR,
        UPDATED_AT_ATTR, STATUS_ATTR, DEGRADED_ATTR, USER_ID_ATTR,
        PROJECT_ID_ATTR, TRUST_ID_ATTR, RESERVATIONS_ATTR, EVENTS_ATTR,
    ) = (
        'name', 'start_date', 'end_date', 'created_at',
        'updated_at', 'status', 'degraded', 'user_id',
        'project_id', 'trust_id', 'reservations', 'events',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the lease.'),
            required=True,
        ),
        START_DATE: properties.Schema(
            properties.Schema.STRING,
            _('The start date and time of the lease. '
              'The date and time format must be "CCYY-MM-DD hh:mm".'),
            required=True,
            constraints=[
                constraints.AllowedPattern(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}'),
            ],
        ),
        END_DATE: properties.Schema(
            properties.Schema.STRING,
            _('The end date and time of the lease '
              'The date and time format must be "CCYY-MM-DD hh:mm".'),
            required=True,
            constraints=[
                constraints.AllowedPattern(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}'),
            ],
        ),
        BEFORE_END_DATE: properties.Schema(
            properties.Schema.STRING,
            _('The date and time for the before-end-action of the lease. '
              'The date and time format must be "CCYY-MM-DD hh:mm".'),
            constraints=[
                constraints.AllowedPattern(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}'),
            ],
        ),
        RESERVATIONS: properties.Schema(
            properties.Schema.LIST,
            _('The list of reservations.'),
            required=True,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    RESOURCE_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        _('The type of the resource to reserve.'),
                        required=True,
                        constraints=[
                            constraints.AllowedValues(['virtual:instance',
                                                       'physical:host'])
                        ]
                    ),
                    MIN: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The minimum number of hosts to reserve.'),
                        constraints=[
                            constraints.Range(min=1)
                        ],
                    ),
                    MAX: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The maximum number of hosts to reserve.'),
                        constraints=[
                            constraints.Range(min=1)
                        ],
                    ),
                    HYPERVISOR_PROPERTIES: properties.Schema(
                        properties.Schema.STRING,
                        _('Properties of the hypervisor to reserve.'),
                    ),
                    RESOURCE_PROPERTIES: properties.Schema(
                        properties.Schema.STRING,
                        _('Properties of the resource to reserve.'),
                    ),
                    BEFORE_END: properties.Schema(
                        properties.Schema.STRING,
                        _('The before-end-action of the reservation.'),
                        default="default",
                        constraints=[
                            constraints.AllowedValues(['default',
                                                       'snapshot'])
                        ]
                    ),
                    AMOUNT: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The amount of instances to reserve.'),
                        constraints=[
                            constraints.Range(min=0, max=2147483647)
                        ],
                    ),

                    VCPUS: properties.Schema(
                        properties.Schema.INTEGER,
                        _('The number of VCPUs per the instance.'),
                        constraints=[
                            constraints.Range(min=0, max=2147483647)
                        ],
                    ),
                    MEMORY_MB: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Megabytes of memory per the instance.'),
                        constraints=[
                            constraints.Range(min=0, max=2147483647)
                        ],
                    ),
                    DISK_GB: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Gigabytes of the local disk per the instance.'),
                        constraints=[
                            constraints.Range(min=0, max=2147483647)
                        ],
                    ),
                    AFFINITY: properties.Schema(
                        properties.Schema.BOOLEAN,
                        _('The affinity of instances to reserve.'),
                        default=False,
                    ),
                },
            ),
        ),
        EVENTS: properties.Schema(
            properties.Schema.LIST,
            _('A list of event objects.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    EVENT_TYPE: properties.Schema(
                        properties.Schema.STRING,
                        _('The type of the event (e.g. notification).'),
                        required=True,
                    ),
                    TIME: properties.Schema(
                        properties.Schema.STRING,
                        _('The date and time of the event. '
                          'The date and time format must be '
                          '"CCYY-MM-DD hh:mm".'),
                        required=True,
                    ),
                },
            ),
        ),

    }

    attributes_schema = {
        NAME_ATTR: attributes.Schema(
            _('The name of the lease.'),
            type=attributes.Schema.STRING
        ),
        START_DATE_ATTR: attributes.Schema(
            _('The start date and time of the lease. '
              'The date and time format is "CCYY-MM-DD hh:mm".'),
            type=attributes.Schema.STRING
        ),
        END_DATE_ATTR: attributes.Schema(
            _('The end date and time of the lease. '
              'The date and time format is "CCYY-MM-DD hh:mm".'),
            type=attributes.Schema.STRING
        ),
        CREATED_AT_ATTR: attributes.Schema(
            _('The date and time when the lease was created. '
              'The date and time format is "CCYY-MM-DD hh:mm".'),
            type=attributes.Schema.STRING
        ),
        UPDATED_AT_ATTR: attributes.Schema(
            _('The date and time when the lease was updated. '
              'The date and time format is "CCYY-MM-DD hh:mm".'),
            type=attributes.Schema.STRING
        ),
        STATUS_ATTR: attributes.Schema(
            _('The status of the lease.'),
            type=attributes.Schema.STRING
        ),
        DEGRADED_ATTR: attributes.Schema(
            _('The flag which represents condition of reserved resources of '
              'the lease. If it is true, the amount of reserved resources is '
              'less than the request or reserved resources were changed.'),
            type=attributes.Schema.BOOLEAN
        ),
        USER_ID_ATTR: attributes.Schema(
            _('The UUID of the lease owner.'),
            type=attributes.Schema.STRING
        ),
        PROJECT_ID_ATTR: attributes.Schema(
            _('The UUID the project which owns the lease.'),
            type=attributes.Schema.STRING
        ),
        TRUST_ID_ATTR: attributes.Schema(
            _('The UUID of the trust of the lease owner.'),
            type=attributes.Schema.STRING
        ),
        RESERVATIONS_ATTR: attributes.Schema(
            _('A list of reservation objects.'),
            type=attributes.Schema.LIST
        ),
        EVENTS_ATTR: attributes.Schema(
            _('Event information of the lease.'),
            type=attributes.Schema.LIST
        ),
    }

    default_client_name = 'blazar'

    entity = 'lease'

    def validate(self):
        super(Lease, self).validate()
        if not self.client_plugin().has_host():
            msg = ("Couldn't find any host in Blazar. "
                   "You must create a host before creating a lease.")
            raise exception.StackValidationFailed(message=msg)

    def _parse_reservation(self, rsv):
        if rsv['resource_type'] == "physical:host":
            for key in ['vcpus', 'memory_mb', 'disk_gb', 'affinity', 'amount']:
                rsv.pop(key)
        elif rsv['resource_type'] == "virtual:instance":
            for key in ['hypervisor_properties', 'max', 'min', 'before_end']:
                rsv.pop(key)

        return rsv

    def handle_create(self):
        args = dict((k, v) for k, v in self.properties.items()
                    if v is not None)
        # rename keys
        args['start'] = args.pop('start_date')
        args['end'] = args.pop('end_date')

        # parse reservations
        args['reservations'] = [self._parse_reservation(rsv)
                                for rsv in args['reservations']]
        lease = self.client_plugin().create_lease(**args)
        self.resource_id_set(lease['id'])
        return lease['id']

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        lease = self.client_plugin().get_lease(self.resource_id)
        try:
            return lease[name]
        except KeyError:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=name)


def resource_mapping():
    return {
        'OS::Blazar::Lease': Lease
    }
