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

from oslo_utils import reflection

import heat.api.openstack.v1 as api_v1
from heat.tests import common


class RoutesTest(common.HeatTestCase):

    def assertRoute(self, mapper, path, method, action, controller,
                    params=None):
        params = params or {}
        route = mapper.match(path, {'REQUEST_METHOD': method})
        self.assertIsNotNone(route)
        self.assertEqual(action, route['action'])
        class_name = reflection.get_class_name(route['controller'].controller,
                                               fully_qualified=False)
        self.assertEqual(controller, class_name)
        del(route['action'])
        del(route['controller'])
        self.assertEqual(params, route)

    def setUp(self):
        super(RoutesTest, self).setUp()
        self.m = api_v1.API({}).map

    def test_template_handling(self):
        self.assertRoute(
            self.m,
            '/aaaa/resource_types',
            'GET',
            'list_resource_types',
            'StackController',
            {
                'tenant_id': 'aaaa',
            })

        self.assertRoute(
            self.m,
            '/aaaa/resource_types/test_type',
            'GET',
            'resource_schema',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'type_name': 'test_type'
            })

        self.assertRoute(
            self.m,
            '/aaaa/resource_types/test_type/template',
            'GET',
            'generate_template',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'type_name': 'test_type'
            })

        self.assertRoute(
            self.m,
            '/aaaa/validate',
            'POST',
            'validate_template',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })

    def test_stack_collection(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks',
            'GET',
            'index',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks',
            'POST',
            'create',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/preview',
            'POST',
            'preview',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/detail',
            'GET',
            'detail',
            'StackController',
            {
                'tenant_id': 'aaaa'
            })

    def test_stack_data(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/arn:openstack:heat::6548ab64fbda49deb188851a3b7d8c8b'
            ':stacks/stack-1411-06/1c5d9bb2-3464-45e2-a728-26dfa4e1d34a',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'arn:openstack:heat:'
                ':6548ab64fbda49deb188851a3b7d8c8b:stacks/stack-1411-06/'
                '1c5d9bb2-3464-45e2-a728-26dfa4e1d34a'
            })

        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/resources',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'resources'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/events',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'events'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb',
            'GET',
            'show',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })

    def test_stack_snapshot(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots',
            'POST',
            'snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots/cccc',
            'GET',
            'show_snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'snapshot_id': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots/cccc',
            'DELETE',
            'delete_snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'snapshot_id': 'cccc'
            })

        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots',
            'GET',
            'list_snapshots',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb'
            })

        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/snapshots/cccc/restore',
            'POST',
            'restore_snapshot',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'snapshot_id': 'cccc'
            })

    def test_stack_outputs(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/outputs',
            'GET',
            'list_outputs',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb'
            }
        )

        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/outputs/cccc',
            'GET',
            'show_output',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'output_key': 'cccc'
            }
        )

    def test_stack_data_template(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/template',
            'GET',
            'template',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/template',
            'GET',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'template'
            })

    def test_stack_post_actions(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/actions',
            'POST',
            'action',
            'ActionController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })

    def test_stack_post_actions_lookup_redirect(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/actions',
            'POST',
            'lookup',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'path': 'actions'
            })

    def test_stack_update_delete(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb',
            'PUT',
            'update',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb',
            'DELETE',
            'delete',
            'StackController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
            })

    def test_resources(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources',
            'GET',
            'index',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc',
            'GET',
            'show',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/metadata',
            'GET',
            'metadata',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/signal',
            'POST',
            'signal',
            'ResourceController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })

    def test_events(self):
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/events',
            'GET',
            'index',
            'EventController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/events',
            'GET',
            'index',
            'EventController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc'
            })
        self.assertRoute(
            self.m,
            '/aaaa/stacks/teststack/bbbb/resources/cccc/events/dddd',
            'GET',
            'show',
            'EventController',
            {
                'tenant_id': 'aaaa',
                'stack_name': 'teststack',
                'stack_id': 'bbbb',
                'resource_name': 'cccc',
                'event_id': 'dddd'
            })

    def test_software_configs(self):
        self.assertRoute(
            self.m,
            '/aaaa/software_configs',
            'GET',
            'index',
            'SoftwareConfigController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_configs',
            'POST',
            'create',
            'SoftwareConfigController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_configs/bbbb',
            'GET',
            'show',
            'SoftwareConfigController',
            {
                'tenant_id': 'aaaa',
                'config_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_configs/bbbb',
            'DELETE',
            'delete',
            'SoftwareConfigController',
            {
                'tenant_id': 'aaaa',
                'config_id': 'bbbb'
            })

    def test_software_deployments(self):
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments',
            'GET',
            'index',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments',
            'POST',
            'create',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments/bbbb',
            'GET',
            'show',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa',
                'deployment_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments/bbbb',
            'PUT',
            'update',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa',
                'deployment_id': 'bbbb'
            })
        self.assertRoute(
            self.m,
            '/aaaa/software_deployments/bbbb',
            'DELETE',
            'delete',
            'SoftwareDeploymentController',
            {
                'tenant_id': 'aaaa',
                'deployment_id': 'bbbb'
            })

    def test_build_info(self):
        self.assertRoute(
            self.m,
            '/fake_tenant/build_info',
            'GET',
            'build_info',
            'BuildInfoController',
            {'tenant_id': 'fake_tenant'}
        )

    def test_405(self):
        self.assertRoute(
            self.m,
            '/fake_tenant/validate',
            'GET',
            'reject',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'allowed_methods': 'POST'}
        )
        self.assertRoute(
            self.m,
            '/fake_tenant/stacks',
            'PUT',
            'reject',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'allowed_methods': 'GET,POST'}
        )
        self.assertRoute(
            self.m,
            '/fake_tenant/stacks/fake_stack/stack_id',
            'POST',
            'reject',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'stack_name': 'fake_stack',
             'stack_id': 'stack_id', 'allowed_methods': 'GET,PUT,PATCH,DELETE'}
        )

    def test_options(self):
        self.assertRoute(
            self.m,
            '/fake_tenant/validate',
            'OPTIONS',
            'options',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'allowed_methods': 'POST'}
        )
        self.assertRoute(
            self.m,
            '/fake_tenant/stacks/fake_stack/stack_id',
            'OPTIONS',
            'options',
            'DefaultMethodController',
            {'tenant_id': 'fake_tenant', 'stack_name': 'fake_stack',
             'stack_id': 'stack_id', 'allowed_methods': 'GET,PUT,PATCH,DELETE'}
        )

    def test_services(self):
        self.assertRoute(
            self.m,
            '/aaaa/services',
            'GET',
            'index',
            'ServiceController',
            {
                'tenant_id': 'aaaa'
            })
