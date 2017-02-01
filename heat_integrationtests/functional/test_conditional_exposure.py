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
parameters:
  instance_type:
    type: string
resources:
  not_available:
    type: OS::Sahara::NodeGroupTemplate
    properties:
      plugin_name: fake
      hadoop_version: 0.1
      flavor: {get_param: instance_type}
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
        parameters = {'instance_type': self.conf.minimal_instance_type}
        ex = self.assertRaises(exc.HTTPBadRequest,
                               self.client.stacks.create,
                               stack_name=stack_name,
                               parameters=parameters,
                               template=self.unavailable_template)
        self.assertIn('ResourceTypeUnavailable', ex.message.decode('utf-8'))
        self.assertIn('OS::Sahara::NodeGroupTemplate',
                      ex.message.decode('utf-8'))


class RoleBasedExposureTest(functional_base.FunctionalTestsBase):

    fl_tmpl = """
heat_template_version: 2015-10-15

resources:
  not4everyone:
    type: OS::Nova::Flavor
    properties:
      ram: 20000
      vcpus: 10
"""

    cvt_tmpl = """
heat_template_version: 2015-10-15

resources:
  cvt:
    type: OS::Cinder::VolumeType
    properties:
      name: cvt_test
"""

    host_aggr_tmpl = """
heat_template_version: 2015-10-15
parameters:
  az:
    type: string
    default: nova
resources:
  cvt:
    type: OS::Nova::HostAggregate
    properties:
      name: aggregate_test
      availability_zone: {get_param: az}
"""

    scenarios = [
        ('r_nova_flavor', dict(
            stack_name='s_nova_flavor',
            template=fl_tmpl,
            forbidden_r_type="OS::Nova::Flavor",
            test_creation=True)),
        ('r_nova_host_aggregate', dict(
            stack_name='s_nova_ost_aggregate',
            template=host_aggr_tmpl,
            forbidden_r_type="OS::Nova::HostAggregate",
            test_creation=True)),
        ('r_cinder_vtype', dict(
            stack_name='s_cinder_vtype',
            template=cvt_tmpl,
            forbidden_r_type="OS::Cinder::VolumeType",
            test_creation=True)),
        ('r_cinder_vtype_encrypt', dict(
            forbidden_r_type="OS::Cinder::EncryptedVolumeType",
            test_creation=False)),
        ('r_neutron_qos', dict(
            forbidden_r_type="OS::Neutron::QoSPolicy",
            test_creation=False)),
        ('r_neutron_qos_bandwidth_limit', dict(
            forbidden_r_type="OS::Neutron::QoSBandwidthLimitRule",
            test_creation=False)),
        ('r_manila_share_type', dict(
            forbidden_r_type="OS::Manila::ShareType",
            test_creation=False))
    ]

    def test_non_admin_forbidden_create_resources(self):
        """Fail to create resource w/o admin role.

        Integration tests job runs as normal OpenStack user,
        and the resources above are configured to require
        admin role in default policy file of Heat.
        """
        if self.test_creation:
            ex = self.assertRaises(exc.Forbidden,
                                   self.client.stacks.create,
                                   stack_name=self.stack_name,
                                   template=self.template)
            self.assertIn(self.forbidden_r_type, ex.message.decode('utf-8'))

    def test_forbidden_resource_not_listed(self):
        resources = self.client.resource_types.list()
        self.assertNotIn(self.forbidden_r_type,
                         (r.resource_type for r in resources))
