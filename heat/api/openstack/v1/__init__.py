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

import routes
import gettext

gettext.install('heat', unicode=1)

from heat.api.openstack.v1 import stacks
from heat.api.openstack.v1 import resources
from heat.common import wsgi

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class API(wsgi.Router):

    """
    WSGI router for Heat v1 ReST API requests.
    """

    def __init__(self, conf, **local_conf):
        self.conf = conf
        mapper = routes.Mapper()

        stacks_resource = stacks.create_resource(conf)

        with mapper.submapper(controller=stacks_resource,
                              path_prefix="/{tenant_id}") as stack_mapper:
            # Template handling
            stack_mapper.connect("template_validate",
                                 "/validate",
                                 action="validate_template",
                                 conditions={'method': 'POST'})

            # Stack collection
            stack_mapper.connect("stack_index",
                                 "/stacks",
                                 action="index",
                                 conditions={'method': 'GET'})
            stack_mapper.connect("stack_create",
                                 "/stacks",
                                 action="create",
                                 conditions={'method': 'POST'})

            # Stack data
            stack_mapper.connect("stack_lookup",
                                 "/stacks/{stack_name}",
                                 action="lookup")
            stack_mapper.connect("stack_lookup_subpath",
                                 "/stacks/{stack_name}/{path:resources}",
                                 action="lookup",
                                 conditions={'method': 'GET'})
            stack_mapper.connect("stack_show",
                                 "/stacks/{stack_name}/{stack_id}",
                                 action="show",
                                 conditions={'method': 'GET'})
            stack_mapper.connect("stack_template",
                                 "/stacks/{stack_name}/{stack_id}/template",
                                 action="template",
                                 conditions={'method': 'GET'})

            # Stack update/delete
            stack_mapper.connect("stack_update",
                                 "/stacks/{stack_name}/{stack_id}",
                                 action="update",
                                 conditions={'method': 'PUT'})
            stack_mapper.connect("stack_delete",
                                 "/stacks/{stack_name}/{stack_id}",
                                 action="delete",
                                 conditions={'method': 'DELETE'})

        # Resources
        resources_resource = resources.create_resource(conf)
        stack_path = "/{tenant_id}/stacks/{stack_name}/{stack_id}"
        with mapper.submapper(controller=resources_resource,
                              path_prefix=stack_path) as res_mapper:

            # Resource collection
            res_mapper.connect("resource_index",
                               "/resources",
                               action="index",
                               conditions={'method': 'GET'})

            # Resource data
            res_mapper.connect("resource_show",
                               "/resources/{resource_name}",
                               action="show",
                               conditions={'method': 'GET'})
            res_mapper.connect("resource_metadata_show",
                               "/resources/{resource_name}/metadata",
                               action="metadata",
                               conditions={'method': 'GET'})

        super(API, self).__init__(mapper)
