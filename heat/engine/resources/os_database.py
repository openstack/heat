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
from heat.openstack.common import log as logging
from heat.openstack.common import uuidutils

LOG = logging.getLogger(__name__)


class OSDBInstance(resource.Resource):
    '''
    OpenStack cloud database instance resource.
    '''

    TROVE_STATUS = (
        ERROR, FAILED, ACTIVE,
    ) = (
        'ERROR', 'FAILED', 'ACTIVE',
    )

    BAD_STATUSES = (ERROR, FAILED)

    PROPERTIES = (
        NAME, FLAVOR, SIZE, DATABASES, USERS, AVAILABILITY_ZONE,
        RESTORE_POINT, DATASTORE_TYPE, DATASTORE_VERSION, NICS,
    ) = (
        'name', 'flavor', 'size', 'databases', 'users', 'availability_zone',
        'restore_point', 'datastore_type', 'datastore_version', 'networks',
    )

    _DATABASE_KEYS = (
        DATABASE_CHARACTER_SET, DATABASE_COLLATE, DATABASE_NAME,
    ) = (
        'character_set', 'collate', 'name',
    )

    _USER_KEYS = (
        USER_NAME, USER_PASSWORD, USER_HOST, USER_DATABASES,
    ) = (
        'name', 'password', 'host', 'databases',
    )

    _NICS_KEYS = (
        NET, PORT, V4_FIXED_IP
    ) = (
        'network', 'port', 'fixed_ip'
    )

    ATTRIBUTES = (
        HOSTNAME, HREF,
    ) = (
        'hostname', 'href',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the DB instance to create.'),
            constraints=[
                constraints.Length(max=255),
            ]
        ),
        FLAVOR: properties.Schema(
            properties.Schema.STRING,
            _('Reference to a flavor for creating DB instance.'),
            required=True
        ),
        DATASTORE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _("Name of registered datastore type."),
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
            constraints=[constraints.Length(max=255)]
        ),
        SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Database volume size in GB.'),
            required=True,
            constraints=[
                constraints.Range(1, 150),
            ]
        ),
        NICS: properties.Schema(
            properties.Schema.LIST,
            _("List of network interfaces to create on instance."),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    NET: properties.Schema(
                        properties.Schema.STRING,
                        _('Name or UUID of the network to attach this NIC to. '
                          'Either %(port)s or %(net)s must be specified.') % {
                              'port': PORT, 'net': NET}
                    ),
                    PORT: properties.Schema(
                        properties.Schema.STRING,
                        _('Name or UUID of Neutron port to attach this '
                          'NIC to. '
                          'Either %(port)s or %(net)s must be specified.') % {
                              'port': PORT, 'net': NET}
                    ),
                    V4_FIXED_IP: properties.Schema(
                        properties.Schema.STRING,
                        _('Fixed IPv4 address for this NIC.')
                    ),
                },
            ),
        ),
        DATABASES: properties.Schema(
            properties.Schema.LIST,
            _('List of databases to be created on DB instance creation.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    DATABASE_CHARACTER_SET: properties.Schema(
                        properties.Schema.STRING,
                        _('Set of symbols and encodings.'),
                        default='utf8'
                    ),
                    DATABASE_COLLATE: properties.Schema(
                        properties.Schema.STRING,
                        _('Set of rules for comparing characters in a '
                          'character set.'),
                        default='utf8_general_ci'
                    ),
                    DATABASE_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('Specifies database names for creating '
                          'databases on instance creation.'),
                        required=True,
                        constraints=[
                            constraints.Length(max=64),
                            constraints.AllowedPattern(r'[a-zA-Z0-9_]+'
                                                       r'[a-zA-Z0-9_@?#\s]*'
                                                       r'[a-zA-Z0-9_]+'),
                        ]
                    ),
                },
            )
        ),
        USERS: properties.Schema(
            properties.Schema.LIST,
            _('List of users to be created on DB instance creation.'),
            default=[],
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    USER_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('User name to create a user on instance '
                          'creation.'),
                        required=True,
                        constraints=[
                            constraints.Length(max=16),
                            constraints.AllowedPattern(r'[a-zA-Z0-9_]+'
                                                       r'[a-zA-Z0-9_@?#\s]*'
                                                       r'[a-zA-Z0-9_]+'),
                        ]
                    ),
                    USER_PASSWORD: properties.Schema(
                        properties.Schema.STRING,
                        _('Password for those users on instance '
                          'creation.'),
                        required=True,
                        constraints=[
                            constraints.AllowedPattern(r'[a-zA-Z0-9_]+'
                                                       r'[a-zA-Z0-9_@?#\s]*'
                                                       r'[a-zA-Z0-9_]+'),
                        ]
                    ),
                    USER_HOST: properties.Schema(
                        properties.Schema.STRING,
                        _('The host from which a user is allowed to '
                          'connect to the database.'),
                        default='%'
                    ),
                    USER_DATABASES: properties.Schema(
                        properties.Schema.LIST,
                        _('Names of databases that those users can '
                          'access on instance creation.'),
                        schema=properties.Schema(
                            properties.Schema.STRING,
                        ),
                        required=True,
                        constraints=[
                            constraints.Length(min=1),
                        ]
                    ),
                },
            )
        ),
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('Name of the availability zone for DB instance.')
        ),
        RESTORE_POINT: properties.Schema(
            properties.Schema.STRING,
            _('DB instance restore point.')
        ),
    }

    attributes_schema = {
        HOSTNAME: attributes.Schema(
            _("Hostname of the instance.")
        ),
        HREF: attributes.Schema(
            _("Api endpoint reference of the instance.")
        ),
    }

    default_client_name = 'trove'

    def __init__(self, name, json_snippet, stack):
        super(OSDBInstance, self).__init__(name, json_snippet, stack)
        self._href = None
        self._dbinstance = None

    @property
    def dbinstance(self):
        """Get the trove dbinstance."""
        if not self._dbinstance and self.resource_id:
            self._dbinstance = self.trove().instances.get(self.resource_id)

        return self._dbinstance

    def _dbinstance_name(self):
        name = self.properties.get(self.NAME)
        if name:
            return name

        return self.physical_resource_name()

    def handle_create(self):
        '''
        Create cloud database instance.
        '''
        self.flavor = self.client_plugin().get_flavor_id(
            self.properties[self.FLAVOR])
        self.volume = {'size': self.properties[self.SIZE]}
        self.databases = self.properties.get(self.DATABASES)
        self.users = self.properties.get(self.USERS)
        restore_point = self.properties.get(self.RESTORE_POINT)
        if restore_point:
            restore_point = {"backupRef": restore_point}
        zone = self.properties.get(self.AVAILABILITY_ZONE)
        self.datastore_type = self.properties.get(self.DATASTORE_TYPE)
        self.datastore_version = self.properties.get(self.DATASTORE_VERSION)

        # convert user databases to format required for troveclient.
        # that is, list of database dictionaries
        for user in self.users:
            dbs = [{'name': db} for db in user.get(self.USER_DATABASES, [])]
            user[self.USER_DATABASES] = dbs

        # convert networks to format required by troveclient
        nics = []
        for nic in self.properties.get(self.NICS):
            nic_dict = {}
            net = nic.get(self.NET)
            if net:
                if uuidutils.is_uuid_like(net):
                    net_id = net
                else:
                    # using Nova for lookup to cover both neutron and
                    # nova-network cases
                    nova = self.client('nova')
                    net_id = nova.networks.find(label=net).id
                nic_dict['net-id'] = net_id
            port = nic.get(self.PORT)
            if port:
                neutron = self.client_plugin('neutron')
                nic_dict['port-id'] = neutron.find_neutron_resource(
                    self.properties, self.PORT, 'port')
            ip = nic.get(self.V4_FIXED_IP)
            if ip:
                nic_dict['v4-fixed-ip'] = ip
            nics.append(nic_dict)

        # create db instance
        instance = self.trove().instances.create(
            self._dbinstance_name(),
            self.flavor,
            volume=self.volume,
            databases=self.databases,
            users=self.users,
            restorePoint=restore_point,
            availability_zone=zone,
            datastore=self.datastore_type,
            datastore_version=self.datastore_version,
            nics=nics)
        self.resource_id_set(instance.id)

        return instance

    def _refresh_instance(self, instance):
        try:
            instance.get()
        except Exception as exc:
            if self.client_plugin().is_over_limit(exc):
                msg = _("Stack %(name)s (%(id)s) received an OverLimit "
                        "response during instance.get(): %(exception)s")
                LOG.warning(msg % {'name': self.stack.name,
                                   'id': self.stack.id,
                                   'exception': exc})
            else:
                raise

    def check_create_complete(self, instance):
        '''
        Check if cloud DB instance creation is complete.
        '''
        self._refresh_instance(instance)  # get updated attributes
        if instance.status in self.BAD_STATUSES:
            raise resource.ResourceInError(
                resource_status=instance.status)

        if instance.status != self.ACTIVE:
            return False

        msg = _("Database instance %(database)s created (flavor:%(flavor)s, "
                "volume:%(volume)s, datastore:%(datastore_type)s, "
                "datastore_version:%(datastore_version)s)")

        LOG.info(msg % {'database': self._dbinstance_name(),
                        'flavor': self.flavor,
                        'volume': self.volume,
                        'datastore_type': self.datastore_type,
                        'datastore_version': self.datastore_version})
        return True

    def handle_delete(self):
        '''
        Delete a cloud database instance.
        '''
        if not self.resource_id:
            return

        instance = None
        try:
            instance = self.trove().instances.get(self.resource_id)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
        else:
            instance.delete()
            return instance

    def check_delete_complete(self, instance):
        '''
        Check for completion of cloud DB instance deletion
        '''
        if not instance:
            return True

        try:
            # For some time trove instance may continue to live
            self._refresh_instance(instance)
        except Exception as ex:
            self.client_plugin().ignore_not_found(ex)
            return True

        return False

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(OSDBInstance, self).validate()
        if res:
            return res

        datastore_type = self.properties.get(self.DATASTORE_TYPE)
        datastore_version = self.properties.get(self.DATASTORE_VERSION)

        if datastore_type:
            # get current active versions
            allowed_versions = self.trove().datastore_versions.list(
                datastore_type)
            allowed_version_names = [v.name for v in allowed_versions]
            if datastore_version:
                if datastore_version not in allowed_version_names:
                    msg = _("Datastore version %(dsversion)s "
                            "for datastore type %(dstype)s is not valid. "
                            "Allowed versions are %(allowed)s.") % {
                                'dstype': datastore_type,
                                'dsversion': datastore_version,
                                'allowed': ', '.join(allowed_version_names)}
                    raise exception.StackValidationFailed(message=msg)
            else:
                if len(allowed_versions) > 1:
                    msg = _("Multiple active datastore versions exist for "
                            "datastore type %(dstype)s. "
                            "Explicit datastore version must be provided. "
                            "Allowed versions are %(allowed)s.") % {
                                'dstype': datastore_type,
                                'allowed': ', '.join(allowed_version_names)}
                    raise exception.StackValidationFailed(message=msg)
        else:
            if datastore_version:
                msg = _("Not allowed - %(dsver)s without %(dstype)s.") % {
                    'dsver': self.DATASTORE_VERSION,
                    'dstype': self.DATASTORE_TYPE}
                raise exception.StackValidationFailed(message=msg)

        # check validity of user and databases
        users = self.properties.get(self.USERS)
        if users:
            databases = self.properties.get(self.DATABASES)
            if not databases:
                msg = _('Databases property is required if users property '
                        'is provided for resource %s.') % self.name
                raise exception.StackValidationFailed(message=msg)

            db_names = set([db[self.DATABASE_NAME] for db in databases])
            for user in users:
                missing_db = [db_name for db_name in user[self.USER_DATABASES]
                              if db_name not in db_names]

                if missing_db:
                    msg = (_('Database %(dbs)s specified for user does '
                             'not exist in databases for resource %(name)s.')
                           % {'dbs': missing_db, 'name': self.name})
                    raise exception.StackValidationFailed(message=msg)

        # check validity of NICS
        is_neutron = self.is_using_neutron()
        nics = self.properties.get(self.NICS)
        for nic in nics:
            if not is_neutron and nic.get(self.PORT):
                msg = _("Can not use %s property on Nova-network.") % self.PORT
                raise exception.StackValidationFailed(message=msg)

            if bool(nic.get(self.NET)) == bool(nic.get(self.PORT)):
                msg = _("Either %(net)s or %(port)s must be provided.") % {
                    'net': self.NET, 'port': self.PORT}
                raise exception.StackValidationFailed(message=msg)

    def href(self):
        if not self._href and self.dbinstance:
            if not self.dbinstance.links:
                self._href = None
            else:
                for link in self.dbinstance.links:
                    if link['rel'] == 'self':
                        self._href = link[self.HREF]
                        break

        return self._href

    def _resolve_attribute(self, name):
        if name == self.HOSTNAME:
            return self.dbinstance.hostname
        elif name == self.HREF:
            return self.href()


def resource_mapping():
    return {
        'OS::Trove::Instance': OSDBInstance,
    }
