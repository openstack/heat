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
"""Utilities for Resources that use the OpenStack Glance API."""

from glanceclient import exc as glance_exceptions

from heat.common import exception
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging
from heat.openstack.common import uuidutils

logger = logging.getLogger(__name__)


def get_image_id(glance_client, image_identifier):
    '''
    Return an id for the specified image name or identifier.

    :param glance_client: the glance client to use
    :param image_identifier: image name or a UUID-like identifier
    :returns: the id of the requested :image_identifier:
    :raises: exception.ImageNotFound, exception.PhysicalResourceNameAmbiguity
    '''
    if uuidutils.is_uuid_like(image_identifier):
        try:
            image_id = glance_client.images.get(image_identifier).id
        except glance_exceptions.NotFound:
            image_id = get_image_id_by_name(glance_client, image_identifier)
    else:
        image_id = get_image_id_by_name(glance_client, image_identifier)
    return image_id


def get_image_id_by_name(glance_client, image_identifier):
    '''
    Return an id for the specified image name or identifier.

    :param glance_client: the glance client to use
    :param image_identifier: image name or a UUID-like identifier
    :returns: the id of the requested :image_identifier:
    :raises: exception.ImageNotFound, exception.PhysicalResourceNameAmbiguity
    '''
    try:
        filters = {'name': image_identifier}
        image_list = list(glance_client.images.list(filters=filters))
    except glance_exceptions.ClientException as ex:
        raise exception.Error(
            _("Error retrieving image list from glance: %s") % ex)
    num_matches = len(image_list)
    if num_matches == 0:
        logger.info(_("Image %s was not found in glance") %
                    image_identifier)
        raise exception.ImageNotFound(image_name=image_identifier)
    elif num_matches > 1:
        logger.info(_("Multiple images %s were found in glance with name")
                    % image_identifier)
        raise exception.PhysicalResourceNameAmbiguity(name=image_identifier)
    else:
        return image_list[0].id
