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

from oslo_utils import uuidutils
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
            'session': con.keystone_session
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

    def get_image_id(self, image_identifier):
        """Return the ID for the specified image name or identifier.

        :param image_identifier: image name or a UUID-like identifier
        :returns: the id of the requested :image_identifier:
        :raises: exception.EntityNotFound,
                 exception.PhysicalResourceNameAmbiguity
        """
        if uuidutils.is_uuid_like(image_identifier):
            try:
                image_id = self.client().images.get(image_identifier).id
            except sahara_base.APIException as ex:
                if self.is_not_registered(ex):
                    image_id = self.get_image_id_by_name(image_identifier)
        else:
            image_id = self.get_image_id_by_name(image_identifier)
        return image_id

    def get_image_id_by_name(self, image_identifier):
        """Return the ID for the specified image name.

        :param image_identifier: image name
        :returns: the id of the requested :image_identifier:
        :raises: exception.EntityNotFound,
                 exception.PhysicalResourceNameAmbiguity
        """
        try:
            filters = {'name': image_identifier}
            image_list = self.client().images.find(**filters)
        except sahara_base.APIException as ex:
            raise exception.Error(
                _("Error retrieving image list from sahara: "
                  "%s") % six.text_type(ex))
        num_matches = len(image_list)
        if num_matches == 0:
            raise exception.EntityNotFound(entity='Image',
                                           name=image_identifier)
        elif num_matches > 1:
            raise exception.PhysicalResourceNameAmbiguity(
                name=image_identifier)
        else:
            return image_list[0].id

    def get_plugin_id(self, plugin_name):
        """Get the id for the specified plugin name.

        :param plugin_name: the name of the plugin to find
        :returns: the id of :plugin:
        :raises: exception.EntityNotFound
        """
        try:
            self.client().plugins.get(plugin_name)
        except sahara_base.APIException:
            raise exception.EntityNotFound(entity='Plugin',
                                           name=plugin_name)


class SaharaBaseConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME


class ImageConstraint(SaharaBaseConstraint):

    expected_exceptions = (exception.EntityNotFound,
                           exception.PhysicalResourceNameAmbiguity,)
    resource_getter_name = 'get_image_id'


class PluginConstraint(SaharaBaseConstraint):

    resource_getter_name = 'get_plugin_id'
