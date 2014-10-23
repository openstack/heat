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

from glanceclient import client as gc
from glanceclient import exc

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients import client_plugin
from heat.engine import constraints
from heat.openstack.common import log as logging
from heat.openstack.common import uuidutils

LOG = logging.getLogger(__name__)


class GlanceClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exc

    def _create(self):

        con = self.context
        endpoint_type = self._get_client_option('glance', 'endpoint_type')
        endpoint = self.url_for(service_type='image',
                                endpoint_type=endpoint_type)
        args = {
            'auth_url': con.auth_url,
            'service_type': 'image',
            'project_id': con.tenant,
            'token': self.auth_token,
            'endpoint_type': endpoint_type,
            'cacert': self._get_client_option('glance', 'ca_file'),
            'cert_file': self._get_client_option('glance', 'cert_file'),
            'key_file': self._get_client_option('glance', 'key_file'),
            'insecure': self._get_client_option('glance', 'insecure')
        }

        return gc.Client('1', endpoint, **args)

    def is_not_found(self, ex):
        return isinstance(ex, exc.HTTPNotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exc.HTTPOverLimit)

    def get_image_id(self, image_identifier):
        '''
        Return an id for the specified image name or identifier.

        :param image_identifier: image name or a UUID-like identifier
        :returns: the id of the requested :image_identifier:
        :raises: exception.ImageNotFound,
                 exception.PhysicalResourceNameAmbiguity
        '''
        if uuidutils.is_uuid_like(image_identifier):
            try:
                image_id = self.client().images.get(image_identifier).id
            except exc.HTTPNotFound:
                image_id = self.get_image_id_by_name(image_identifier)
        else:
            image_id = self.get_image_id_by_name(image_identifier)
        return image_id

    def get_image_id_by_name(self, image_identifier):
        '''
        Return an id for the specified image name.

        :param image_identifier: image name
        :returns: the id of the requested :image_identifier:
        :raises: exception.ImageNotFound,
                 exception.PhysicalResourceNameAmbiguity
        '''
        try:
            filters = {'name': image_identifier}
            image_list = list(self.client().images.list(filters=filters))
        except exc.ClientException as ex:
            raise exception.Error(
                _("Error retrieving image list from glance: %s") % ex)
        num_matches = len(image_list)
        if num_matches == 0:
            LOG.info(_("Image %s was not found in glance") %
                     image_identifier)
            raise exception.ImageNotFound(image_name=image_identifier)
        elif num_matches > 1:
            LOG.info(_("Multiple images %s were found in glance with name") %
                     image_identifier)
            raise exception.PhysicalResourceNameAmbiguity(
                name=image_identifier)
        else:
            return image_list[0].id


class ImageConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.ImageNotFound,)

    def validate_with_client(self, client, value):
        client.client_plugin('glance').get_image_id(value)
