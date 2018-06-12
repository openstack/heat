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

import requests

from heat_integrationtests.functional import functional_base

expected_version_dict = {
    "versions": [
        {"links": [{"href": None, "rel": "self"}],
         "status": "CURRENT", "id": "v1.0"}
    ]
}


class VersionNegotiationTestCase(functional_base.FunctionalTestsBase):

    def test_authless_version_negotiation(self):
        # NOTE(pas-ha): this will grab the public endpoint by default
        heat_url = self.identity_client.get_endpoint_url(
            'orchestration', region=self.conf.region)
        heat_api_root = heat_url.split('/v1')[0]
        expected_version_dict[
            'versions'][0]['links'][0]['href'] = heat_api_root + '/v1/'
        r = requests.get(heat_api_root)
        self.assertEqual(300, r.status_code, 'got response %s' % r.text)
        self.assertEqual(expected_version_dict, r.json())
