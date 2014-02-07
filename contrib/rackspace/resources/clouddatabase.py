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

try:
    from pyrax.exceptions import ClientException
except ImportError:
    # define exception for testing without pyrax
    class ClientException(Exception):
        def __init__(self, code, message=None, details=None, request_id=None):
            self.code = code
            self.message = message or self.__class__.message
            self.details = details
            self.request_id = request_id

        def __str__(self):
            formatted_string = "%s (HTTP %s)" % (self.message, self.code)
            if self.request_id:
                formatted_string += " (Request-ID: %s)" % self.request_id

            return formatted_string

    def resource_mapping():
        return {}
else:

    def resource_mapping():
        return {'Rackspace::Cloud::DBInstance': CloudDBInstance}

from heat.common import exception
from heat.openstack.common import log as logging
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource

logger = logging.getLogger(__name__)


class CloudDBInstance(resource.Resource):
    '''
    Rackspace cloud database resource.
    '''

    PROPERTIES = (
        INSTANCE_NAME, FLAVOR_REF, VOLUME_SIZE, DATABASES, USERS,
    ) = (
        'InstanceName', 'FlavorRef', 'VolumeSize', 'Databases', 'Users',
    )

    _DATABASE_KEYS = (
        DATABASE_CHARACTER_SET, DATABASE_COLLATE, DATABASE_NAME,
    ) = (
        'Character_set', 'Collate', 'Name',
    )

    _USER_KEYS = (
        USER_NAME, USER_PASSWORD, USER_HOST, USER_DATABASES,
    ) = (
        'Name', 'Password', 'Host', 'Databases',
    )

    properties_schema = {
        INSTANCE_NAME: properties.Schema(
            properties.Schema.STRING,
            required=True,
            constraints=[
                constraints.Length(max=255),
            ]
        ),
        FLAVOR_REF: properties.Schema(
            properties.Schema.STRING,
            required=True
        ),
        VOLUME_SIZE: properties.Schema(
            properties.Schema.NUMBER,
            required=True,
            constraints=[
                constraints.Range(1, 150),
            ]
        ),
        DATABASES: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    DATABASE_CHARACTER_SET: properties.Schema(
                        properties.Schema.STRING,
                        default='utf8'
                    ),
                    DATABASE_COLLATE: properties.Schema(
                        properties.Schema.STRING,
                        default='utf8_general_ci'
                    ),
                    DATABASE_NAME: properties.Schema(
                        properties.Schema.STRING,
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
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    USER_NAME: properties.Schema(
                        properties.Schema.STRING,
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
                        required=True,
                        constraints=[
                            constraints.AllowedPattern(r'[a-zA-Z0-9_]+'
                                                       r'[a-zA-Z0-9_@?#\s]*'
                                                       r'[a-zA-Z0-9_]+'),
                        ]
                    ),
                    USER_HOST: properties.Schema(
                        properties.Schema.STRING,
                        default='%'
                    ),
                    USER_DATABASES: properties.Schema(
                        properties.Schema.LIST,
                        required=True
                    ),
                },
            )
        ),
    }

    attributes_schema = {
        "hostname": "Hostname of the instance",
        "href": "Api endpoint reference of the instance"
    }

    def __init__(self, name, json_snippet, stack):
        super(CloudDBInstance, self).__init__(name, json_snippet, stack)
        self.hostname = None
        self.href = None

    def cloud_db(self):
        return self.stack.clients.cloud_db()

    def handle_create(self):
        '''
        Create Rackspace Cloud DB Instance.
        '''
        logger.debug("Cloud DB instance handle_create called")
        self.sqlinstancename = self.properties[self.INSTANCE_NAME]
        self.flavor = self.properties[self.FLAVOR_REF]
        self.volume = self.properties[self.VOLUME_SIZE]
        self.databases = self.properties.get(self.DATABASES, None)
        self.users = self.properties.get(self.USERS, None)

        # create db instance
        logger.info("Creating Cloud DB instance %s" % self.sqlinstancename)
        instance = self.cloud_db().create(self.sqlinstancename,
                                          flavor=self.flavor,
                                          volume=self.volume)
        if instance is not None:
            self.resource_id_set(instance.id)

        self.hostname = instance.hostname
        self.href = instance.links[0]['href']
        return instance

    def check_create_complete(self, instance):
        '''
        Check if cloud DB instance creation is complete.
        '''
        instance.get()  # get updated attributes
        if instance.status == 'ERROR':
            instance.delete()
            raise exception.Error("Cloud DB instance creation failed.")

        if instance.status != 'ACTIVE':
            return False

        logger.info("Cloud DB instance %s created (flavor:%s, volume:%s)" %
                    (self.sqlinstancename, self.flavor, self.volume))
        # create databases
        for database in self.databases:
            instance.create_database(
                database[self.DATABASE_NAME],
                character_set=database[self.DATABASE_CHARACTER_SET],
                collate=database[self.DATABASE_COLLATE])
            logger.info("Database %s created on cloud DB instance %s" %
                        (database[self.DATABASE_NAME], self.sqlinstancename))

        # add users
        dbs = []
        for user in self.users:
            if user[self.USER_DATABASES]:
                dbs = user[self.USER_DATABASES]
            instance.create_user(user[self.DATABASE_NAME],
                                 user[self.USER_PASSWORD],
                                 dbs)
            logger.info("Cloud database user %s created successfully" %
                        (user[self.DATABASE_NAME]))
        return True

    def handle_delete(self):
        '''
        Delete a Rackspace Cloud DB Instance.
        '''
        logger.debug("CloudDBInstance handle_delete called.")
        if self.resource_id is None:
            return
        try:
            self.cloud_db().delete(self.resource_id)
        except ClientException as cexc:
            if str(cexc.code) != "404":
                raise cexc

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(CloudDBInstance, self).validate()
        if res:
            return res

        # check validity of user and databases
        users = self.properties.get(self.USERS, None)
        if not users:
            return

        databases = self.properties.get(self.DATABASES, None)
        if not databases:
            return {'Error':
                    'Databases property is required if Users property'
                    ' is provided'}

        for user in users:
            if not user[self.USER_DATABASES]:
                return {'Error':
                        'Must provide access to at least one database for '
                        'user %s' % user[self.DATABASE_NAME]}

            db_names = set([db[self.DATABASE_NAME] for db in databases])
            missing_db = [db_name for db_name in user[self.USER_DATABASES]
                          if db_name not in db_names]
            if missing_db:
                return {'Error':
                        'Database %s specified for user does not exist in '
                        'databases.' % missing_db}
        return

    def _hostname(self):
        if self.hostname is None and self.resource_id is not None:
            dbinstance = self.cloud_db().get(self.resource_id)
            self.hostname = dbinstance.hostname

        return self.hostname

    def _href(self):
        if self.href is None and self.resource_id is not None:
            dbinstance = self.cloud_db().get(self.resource_id)
            self.href = self._gethref(dbinstance)

        return self.href

    def _gethref(self, dbinstance):
        if dbinstance is None or dbinstance.links is None:
            return None

        for link in dbinstance.links:
            if link['rel'] == 'self':
                return link['href']

    def _resolve_attribute(self, name):
        if name == 'hostname':
            return self._hostname()
        elif name == 'href':
            return self._href()
        else:
            return None
