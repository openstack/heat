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

import logging
import routes

from heat.common import wsgi
from heat.metadata.api.v1 import metadata


class API(wsgi.Router):
    """
    WSGI router for Heat Metadata Server API v1 requests.
    """

    def __init__(self, conf, **local_conf):
        self.cong = conf
        mapper = routes.Mapper()
        metadata_controller = metadata.create_resource(conf)

        mapper.connect('/',
                       controller=metadata_controller, action='entry_point',
                       conditions=dict(method=['GET']))
        mapper.connect('/stacks/',
                       controller=metadata_controller, action='list_stacks',
                       conditions=dict(method=['GET']))
        mapper.connect('/stacks/:stack_name/resources/',
                       controller=metadata_controller, action='list_resources',
                       conditions=dict(method=['GET']))
        mapper.connect('/stacks/:stack_name/resources/:resource_id',
                       controller=metadata_controller, action='get_resource',
                       conditions=dict(method=['GET']))
        mapper.connect('/stacks/:stack_name',
                       controller=metadata_controller, action='create_stack',
                       conditions=dict(method=['PUT']))
        mapper.connect('/stacks/:stack_name/resources/:resource_id',
                       controller=metadata_controller,\
                       action='update_metadata',
                       conditions=dict(method=['PUT']))
        mapper.connect('/events/',
                       controller=metadata_controller, action='create_event',
                       conditions=dict(method=['POST']))
        mapper.connect('/stats/:watch_name/data/',
                       controller=metadata_controller,
                       action='create_watch_data',
                       conditions=dict(method=['POST']))
#        mapper.connect('/stats/:watch_name/data/',
#                       controller=metadata_controller,
#                       action='list_watch_data',
#                       conditions=dict(method=['GET']))

        # TODO(shadower): make sure all responses are JSON-encoded
        # currently, calling an unknown route uses the default handler which
        # produces a HTML response.

        super(API, self).__init__(mapper)
