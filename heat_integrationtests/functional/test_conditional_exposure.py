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

from heatclient import exc
import keystoneclient

from heat_integrationtests.functional import functional_base


class ServiceBasedExposureTest(functional_base.FunctionalTestsBase):
    # NOTE(pas-ha) if we ever decide to install Sahara on Heat
    # functional gate, this must be changed to other not-installed
    # but in principle supported service
    unavailable_service = 'Sahara'
    unavailable_template = """
heat_template_version: 2015-10-15
resources:
  not_available:
    type: OS::Sahara::NodeGroupTemplate
    properties:
      plugin_name: fake
      hadoop_version: 0.1
      flavor: m1.large
      node_processes: []
"""

    def setUp(self):
        super(ServiceBasedExposureTest, self).setUp()
        # check that Sahara endpoint is available
        if self._is_sahara_deployed():
            self.skipTest("Sahara is actually deployed, "
                          "can not run negative tests on "
                          "Sahara resources availability.")

    def _is_sahara_deployed(self):
        try:
            self.identity_client.get_endpoint_url('data-processing',
                                                  self.conf.region)
        except keystoneclient.exceptions.EndpointNotFound:
            return False
        return True

    def test_unavailable_resources_not_listed(self):
        resources = self.client.resource_types.list()
        self.assertFalse(any(self.unavailable_service in r.resource_type
                             for r in resources))

    def test_unavailable_resources_not_created(self):
        stack_name = self._stack_rand_name()
        ex = self.assertRaises(exc.HTTPBadRequest,
                               self.client.stacks.create,
                               stack_name=stack_name,
                               template=self.unavailable_template)
        self.assertIn('ResourceTypeUnavailable', ex.message)
        self.assertIn('OS::Sahara::NodeGroupTemplate', ex.message)


class RoleBasedExposureTest(functional_base.FunctionalTestsBase):
    forbidden_resource_type = "OS::Nova::Flavor"
    fl_tmpl = """
heat_template_version: 2015-10-15

resources:
  not4everyone:
    type: OS::Nova::Flavor
    properties:
      ram: 20000
      vcpus: 10
"""
    fl_tmpl_nested = """
heat_template_version: 2015-10-15
resources:
  not4everyonerg:
    type: OS::Heat::ResourceGroup
    properties:
        count: 1
        resource_def:
            type: OS::Nova::Flavor
            properties:
              ram: 20000
              vcpus: 10
"""

    def test_non_admin_forbidden_create_flavors(self):
        """Fail to create Flavor resource w/o admin role.

        Integration tests job runs as normal OpenStack user,
        and OS::Nova:Flavor is configured to require
        admin role in default policy file of Heat.
        """
        stack_name = self._stack_rand_name()
        ex = self.assertRaises(exc.Forbidden,
                               self.client.stacks.create,
                               stack_name=stack_name,
                               template=self.fl_tmpl)
        self.assertIn(self.forbidden_resource_type, ex.message)

    def test_forbidden_resource_not_listed(self):
        resources = self.client.resource_types.list()
        self.assertNotIn(self.forbidden_resource_type,
                         (r.resource_type for r in resources))

    def test_non_admin_forbidden_create_flavors_nested(self):
        stack_name = self._stack_rand_name()
        ex = self.assertRaises(exc.Forbidden,
                               self.client.stacks.create,
                               stack_name=stack_name,
                               template=self.fl_tmpl_nested)
        self.assertIn(self.forbidden_resource_type, ex.message)
