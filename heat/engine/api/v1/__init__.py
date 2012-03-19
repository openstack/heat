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

from heat.common import wsgi
from heat.engine.api.v1 import stacks

class API(wsgi.Router):
    """WSGI entry point for all stac requests."""

    def __init__(self, conf, **local_conf):
        mapper = routes.Mapper()

        stacks_resource = stacks.create_resource(conf)
        mapper.resource("stack", "stacks", controller=stacks_resource,
                        collection={'detail': 'GET'})
        mapper.connect("/", controller=stacks_resource, action="index")

        super(API, self).__init__(mapper)
