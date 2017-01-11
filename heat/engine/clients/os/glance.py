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

from oslo_utils import uuidutils

from glanceclient import client as gc
from glanceclient import exc

from heat.engine.clients import client_exception
from heat.engine.clients import client_plugin
from heat.engine.clients import os as os_client
from heat.engine import constraints

CLIENT_NAME = 'glance'


class GlanceClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = [client_exception, exc]

    service_types = [IMAGE] = ['image']

    supported_versions = [V1, V2] = ['1', '2']

    default_version = V2

    def _create(self, version=None):
        con = self.context
        interface = self._get_client_option(CLIENT_NAME, 'endpoint_type')

        return gc.Client(version, session=con.keystone_session,
                         interface=interface,
                         service_type=self.IMAGE,
                         region_name=self._get_region_name())

    def _find_with_attr(self, entity, **kwargs):
        """Find a item for entity with attributes matching ``**kwargs``."""
        matches = list(self._findall_with_attr(entity, **kwargs))
        num_matches = len(matches)
        if num_matches == 0:
            raise client_exception.EntityMatchNotFound(entity=entity,
                                                       args=kwargs)
        elif num_matches > 1:
            raise client_exception.EntityUniqueMatchNotFound(entity=entity,
                                                             args=kwargs)
        else:
            return matches[0]

    def _findall_with_attr(self, entity, **kwargs):
        """Find all items for entity with attributes matching ``**kwargs``."""
        func = getattr(self.client(), entity)
        filters = {'filters': kwargs}
        return func.list(**filters)

    def is_not_found(self, ex):
        return isinstance(ex, (client_exception.EntityMatchNotFound,
                               exc.HTTPNotFound))

    def is_over_limit(self, ex):
        return isinstance(ex, exc.HTTPOverLimit)

    def is_conflict(self, ex):
        return isinstance(ex, exc.Conflict)

    def find_image_by_name_or_id(self, image_identifier):
        """Return the ID for the specified image name or identifier.

        :param image_identifier: image name or a UUID-like identifier
        :returns: the id of the requested :image_identifier:
        """
        return self._find_image_id(self.context.tenant_id,
                                   image_identifier)

    @os_client.MEMOIZE_FINDER
    def _find_image_id(self, tenant_id, image_identifier):
        # tenant id in the signature is used for the memoization key,
        # that would differentiate similar resource names across tenants.
        return self.get_image(image_identifier).id

    def get_image(self, image_identifier):
        """Return the image object for the specified image name/id.

        :param image_identifier: image name
        :returns: an image object with name/id :image_identifier:
        """
        if uuidutils.is_uuid_like(image_identifier):
            try:
                return self.client().images.get(image_identifier)
            except exc.HTTPNotFound:
                pass
        return self._find_with_attr('images', name=image_identifier)


class ImageConstraint(constraints.BaseCustomConstraint):
    expected_exceptions = (client_exception.EntityMatchNotFound,
                           client_exception.EntityUniqueMatchNotFound)

    resource_client_name = CLIENT_NAME
    resource_getter_name = 'find_image_by_name_or_id'
