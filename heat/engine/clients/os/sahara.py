# Copyright (c) 2014 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from saharaclient.api import base as sahara_base
from saharaclient import client as sahara_client
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'sahara'


class SaharaClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = sahara_base

    service_types = [DATA_PROCESSING] = ['data-processing']

    def _create(self):
        con = self.context
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'endpoint_type': endpoint_type,
            'service_type': self.DATA_PROCESSING,
            'session': con.keystone_session,
            'region_name': self._get_region_name()
        }
        client = sahara_client.Client('1.1', **args)
        return client

    def validate_hadoop_version(self, plugin_name, hadoop_version):
        plugin = self.client().plugins.get(plugin_name)
        allowed_versions = plugin.versions
        if hadoop_version not in allowed_versions:
            msg = (_("Requested plugin '%(plugin)s' doesn\'t support version "
                     "'%(version)s'. Allowed versions are %(allowed)s") %
                   {'plugin': plugin_name,
                    'version': hadoop_version,
                    'allowed': ', '.join(allowed_versions)})
            raise exception.StackValidationFailed(message=msg)

    def is_not_found(self, ex):
        return (isinstance(ex, sahara_base.APIException) and
                ex.error_code == 404)

    def is_over_limit(self, ex):
        return (isinstance(ex, sahara_base.APIException) and
                ex.error_code == 413)

    def is_conflict(self, ex):
        return (isinstance(ex, sahara_base.APIException) and
                ex.error_code == 409)

    def is_not_registered(self, ex):
        return (isinstance(ex, sahara_base.APIException) and
                ex.error_code == 400 and
                ex.error_name == 'IMAGE_NOT_REGISTERED')

    def find_resource_by_name_or_id(self, resource_name, value):
        """Return the ID for the specified name or identifier.

        :param resource_name: API name of entity
        :param value: ID or name of entity
        :returns: the id of the requested :value:
        :raises exception.EntityNotFound:
        :raises exception.PhysicalResourceNameAmbiguity:
        """
        try:
            entity = getattr(self.client(), resource_name)
            return entity.get(value).id
        except sahara_base.APIException:
            return self.find_resource_by_name(resource_name, value)

    def get_image_id(self, image_identifier):
        """Return the ID for the specified image name or identifier.

        :param image_identifier: image name or a UUID-like identifier
        :returns: the id of the requested :image_identifier:
        :raises exception.EntityNotFound:
        :raises exception.PhysicalResourceNameAmbiguity:
        """
        # leave this method for backward compatibility
        try:
            return self.find_resource_by_name_or_id('images', image_identifier)
        except exception.EntityNotFound:
            raise exception.EntityNotFound(entity='Image',
                                           name=image_identifier)

    def find_resource_by_name(self, resource_name, value):
        """Return the ID for the specified entity name.

        :raises exception.EntityNotFound:
        :raises exception.PhysicalResourceNameAmbiguity:
        """
        try:
            filters = {'name': value}
            obj = getattr(self.client(), resource_name)
            obj_list = obj.find(**filters)
        except sahara_base.APIException as ex:
            raise exception.Error(
                _("Error retrieving %(entity)s list from sahara: "
                  "%(err)s") % dict(entity=resource_name,
                                    err=six.text_type(ex)))
        num_matches = len(obj_list)
        if num_matches == 0:
            raise exception.EntityNotFound(entity=resource_name or 'entity',
                                           name=value)
        elif num_matches > 1:
            raise exception.PhysicalResourceNameAmbiguity(
                name=value)
        else:
            return obj_list[0].id

    def get_plugin_id(self, plugin_name):
        """Get the id for the specified plugin name.

        :param plugin_name: the name of the plugin to find
        :returns: the id of :plugin:
        :raises exception.EntityNotFound:
        """
        try:
            self.client().plugins.get(plugin_name)
        except sahara_base.APIException:
            raise exception.EntityNotFound(entity='Plugin',
                                           name=plugin_name)

    def get_job_type(self, job_type):
        """Find the job type

        :param job_type: the name of sahara job type to find
        :returns: the name of :job_type:
        :raises: exception.EntityNotFound
        """
        try:
            filters = {'name': job_type}
            return self.client().job_types.find_unique(**filters)
        except sahara_base.APIException:
            raise exception.EntityNotFound(entity='Job Type',
                                           name=job_type)


class SaharaBaseConstraint(constraints.BaseCustomConstraint):
    expected_exceptions = (exception.EntityNotFound,
                           exception.PhysicalResourceNameAmbiguity,)
    resource_name = None

    def validate_with_client(self, client, resource_id):
        sahara_plugin = client.client_plugin(CLIENT_NAME)
        sahara_plugin.find_resource_by_name_or_id(self.resource_name,
                                                  resource_id)


class PluginConstraint(constraints.BaseCustomConstraint):
    # do not touch constraint for compatibility
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_plugin_id'


class JobTypeConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_job_type'


class ImageConstraint(SaharaBaseConstraint):
    resource_name = 'images'


class JobBinaryConstraint(SaharaBaseConstraint):
    resource_name = 'job_binaries'


class ClusterConstraint(SaharaBaseConstraint):
    resource_name = 'clusters'


class DataSourceConstraint(SaharaBaseConstraint):
    resource_name = 'data_sources'


class ClusterTemplateConstraint(SaharaBaseConstraint):
    resource_name = 'cluster_templates'
