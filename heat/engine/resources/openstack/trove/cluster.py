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

from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support
from heat.engine import translation

LOG = logging.getLogger(__name__)


class TroveCluster(resource.Resource):
    """A resource for managing Trove clusters.

    A Cluster is an opaque cluster used to store Database clusters.
    """

    support_status = support.SupportStatus(version='2015.1')

    TROVE_STATUS = (
        ERROR, FAILED, ACTIVE,
    ) = (
        'ERROR', 'FAILED', 'ACTIVE',
    )

    DELETE_STATUSES = (
        DELETING, NONE
    ) = (
        'DELETING', 'NONE'
    )

    TROVE_STATUS_REASON = {
        FAILED: _('The database instance was created, but heat failed to set '
                  'up the datastore. If a database instance is in the FAILED '
                  'state, it should be deleted and a new one should be '
                  'created.'),
        ERROR: _('The last operation for the database instance failed due to '
                 'an error.'),
    }

    BAD_STATUSES = (ERROR, FAILED)

    PROPERTIES = (
        NAME, DATASTORE_TYPE, DATASTORE_VERSION, INSTANCES,
    ) = (
        'name', 'datastore_type', 'datastore_version', 'instances',
    )

    _INSTANCE_KEYS = (
        FLAVOR, VOLUME_SIZE, NETWORKS,
    ) = (
        'flavor', 'volume_size', 'networks',
    )

    _NICS_KEYS = (
        NET, PORT, V4_FIXED_IP
    ) = (
        'network', 'port', 'fixed_ip'
    )

    ATTRIBUTES = (
        INSTANCES_ATTR, IP
    ) = (
        'instances', 'ip'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the cluster to create.'),
            constraints=[
                constraints.Length(max=255),
            ]
        ),
        DATASTORE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _("Name of registered datastore type."),
            required=True,
            constraints=[
                constraints.Length(max=255)
            ]
        ),
        DATASTORE_VERSION: properties.Schema(
            properties.Schema.STRING,
            _("Name of the registered datastore version. "
              "It must exist for provided datastore type. "
              "Defaults to using single active version. "
              "If several active versions exist for provided datastore type, "
              "explicit value for this parameter must be specified."),
            required=True,
            constraints=[constraints.Length(max=255)]
        ),
        INSTANCES: properties.Schema(
            properties.Schema.LIST,
            _("List of database instances."),
            required=True,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    FLAVOR: properties.Schema(
                        properties.Schema.STRING,
                        _('Flavor of the instance.'),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('trove.flavor')
                        ]
                    ),
                    VOLUME_SIZE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Size of the instance disk volume in GB.'),
                        required=True,
                        constraints=[
                            constraints.Range(1, 150),
                        ]
                    ),
                    NETWORKS: properties.Schema(
                        properties.Schema.LIST,
                        _("List of network interfaces to create on instance."),
                        support_status=support.SupportStatus(version='10.0.0'),
                        default=[],
                        schema=properties.Schema(
                            properties.Schema.MAP,
                            schema={
                                NET: properties.Schema(
                                    properties.Schema.STRING,
                                    _('Name or UUID of the network to attach '
                                      'this NIC to. Either %(port)s or '
                                      '%(net)s must be specified.') % {
                                        'port': PORT, 'net': NET},
                                    constraints=[
                                        constraints.CustomConstraint(
                                            'neutron.network')
                                    ]
                                ),
                                PORT: properties.Schema(
                                    properties.Schema.STRING,
                                    _('Name or UUID of Neutron port to '
                                      'attach this NIC to. Either %(port)s '
                                      'or %(net)s must be specified.')
                                    % {'port': PORT, 'net': NET},
                                    constraints=[
                                        constraints.CustomConstraint(
                                            'neutron.port')
                                    ],
                                ),
                                V4_FIXED_IP: properties.Schema(
                                    properties.Schema.STRING,
                                    _('Fixed IPv4 address for this NIC.'),
                                    constraints=[
                                        constraints.CustomConstraint('ip_addr')
                                    ]
                                ),
                            },
                        ),
                    ),
                }
            )
        ),
    }

    attributes_schema = {
        INSTANCES: attributes.Schema(
            _("A list of instances ids."),
            type=attributes.Schema.LIST
        ),
        IP: attributes.Schema(
            _("A list of cluster instance IPs."),
            type=attributes.Schema.LIST
        )
    }

    default_client_name = 'trove'

    entity = 'clusters'

    def translation_rules(self, properties):
        return [
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.INSTANCES, self.NETWORKS, self.NET],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='network'),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.INSTANCES, self.NETWORKS, self.PORT],
                client_plugin=self.client_plugin('neutron'),
                finder='find_resourceid_by_name_or_id',
                entity='port'),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.INSTANCES, self.FLAVOR],
                client_plugin=self.client_plugin(),
                finder='find_flavor_by_name_or_id'),
        ]

    def _cluster_name(self):
        return self.properties[self.NAME] or self.physical_resource_name()

    def handle_create(self):
        datastore_type = self.properties[self.DATASTORE_TYPE]
        datastore_version = self.properties[self.DATASTORE_VERSION]

        # convert instances to format required by troveclient
        instances = []
        for instance in self.properties[self.INSTANCES]:
            instance_dict = {
                'flavorRef': instance[self.FLAVOR],
                'volume': {'size': instance[self.VOLUME_SIZE]},
            }
            instance_nics = self.get_instance_nics(instance)
            if instance_nics:
                instance_dict["nics"] = instance_nics
            instances.append(instance_dict)

        args = {
            'name': self._cluster_name(),
            'datastore': datastore_type,
            'datastore_version': datastore_version,
            'instances': instances
        }
        cluster = self.client().clusters.create(**args)
        self.resource_id_set(cluster.id)
        return cluster.id

    def get_instance_nics(self, instance):
        nics = []
        for nic in instance[self.NETWORKS]:
            nic_dict = {}
            if nic.get(self.NET):
                nic_dict['net-id'] = nic.get(self.NET)
            if nic.get(self.PORT):
                nic_dict['port-id'] = nic.get(self.PORT)
            ip = nic.get(self.V4_FIXED_IP)
            if ip:
                nic_dict['v4-fixed-ip'] = ip
            nics.append(nic_dict)

        return nics

    def _refresh_cluster(self, cluster_id):
        try:
            cluster = self.client().clusters.get(cluster_id)
            return cluster
        except Exception as exc:
            if self.client_plugin().is_over_limit(exc):
                LOG.warning("Stack %(name)s (%(id)s) received an "
                            "OverLimit response during clusters.get():"
                            " %(exception)s",
                            {'name': self.stack.name,
                             'id': self.stack.id,
                             'exception': exc})
                return None
            else:
                raise

    def check_create_complete(self, cluster_id):
        cluster = self._refresh_cluster(cluster_id)

        if cluster is None:
            return False

        for instance in cluster.instances:
            if instance['status'] in self.BAD_STATUSES:
                raise exception.ResourceInError(
                    resource_status=instance['status'],
                    status_reason=self.TROVE_STATUS_REASON.get(
                        instance['status'], _("Unknown")))

            if instance['status'] != self.ACTIVE:
                return False

        LOG.info("Cluster '%s' has been created", cluster.name)
        return True

    def cluster_delete(self, cluster_id):
        try:
            cluster = self.client().clusters.get(cluster_id)
            cluster_status = cluster.task['name']
            if cluster_status not in self.DELETE_STATUSES:
                return False
            if cluster_status != self.DELETING:
                # If cluster already started to delete, don't send another one
                # request for deleting.
                cluster.delete()
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        return True

    def handle_delete(self):
        if not self.resource_id:
            return

        try:
            cluster = self.client().clusters.get(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            return cluster.id

    def check_delete_complete(self, cluster_id):
        if not cluster_id:
            return True

        if not self.cluster_delete(cluster_id):
            return False

        try:
            # For some time trove cluster may continue to live
            self._refresh_cluster(cluster_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True

        return False

    def validate(self):
        res = super(TroveCluster, self).validate()
        if res:
            return res

        datastore_type = self.properties[self.DATASTORE_TYPE]
        datastore_version = self.properties[self.DATASTORE_VERSION]

        self.client_plugin().validate_datastore(
            datastore_type, datastore_version,
            self.DATASTORE_TYPE, self.DATASTORE_VERSION)

        # check validity of instances' NETWORKS
        is_neutron = self.is_using_neutron()
        for instance in self.properties[self.INSTANCES]:
            for nic in instance[self.NETWORKS]:
                # 'nic.get(self.PORT) is not None' including two cases:
                # 1. has set port value in template
                # 2. using 'get_resource' to reference a new resource
                if not is_neutron and nic.get(self.PORT) is not None:
                    msg = (_("Can not use %s property on Nova-network.")
                           % self.PORT)
                    raise exception.StackValidationFailed(message=msg)

                if (bool(nic.get(self.NET) is not None) ==
                        bool(nic.get(self.PORT) is not None)):
                    msg = (_("Either %(net)s or %(port)s must be provided.")
                           % {'net': self.NET, 'port': self.PORT})
                    raise exception.StackValidationFailed(message=msg)

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        if name == self.INSTANCES_ATTR:
            instances = []
            cluster = self.client().clusters.get(self.resource_id)
            for instance in cluster.instances:
                instances.append(instance['id'])
            return instances
        elif name == self.IP:
            cluster = self.client().clusters.get(self.resource_id)
            return cluster.ip


def resource_mapping():
    return {
        'OS::Trove::Cluster': TroveCluster
    }
