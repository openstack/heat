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
from heat.db.sqlalchemy import api as db_api
from heat.tests import utils


class RealityStore(object):

    def __init__(self):
        self.cntxt = utils.dummy_context()

    def resources_by_logical_name(self, logical_name):
        ret = []
        resources = db_api.resource_get_all(self.cntxt)
        for res in resources:
            if (res.name == logical_name and res.action in ("CREATE", "UPDATE")
               and res.status == "COMPLETE"):
                ret.append(res)
        return ret

    def all_resources(self):
        try:
            resources = db_api.resource_get_all(self.cntxt)
        except exception.NotFound:
            return []

        ret = []
        for res in resources:
            if res.action in ("CREATE", "UPDATE") and res.status == "COMPLETE":
                ret.append(res)
        return ret

    def resource_properties(self, res, prop_name):
        res_data = db_api.resource_data_get_by_key(self.cntxt,
                                                   res.id,
                                                   prop_name)
        return res_data.value

reality = RealityStore()
