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

import mock
import six

from heat.common import exception
from heat.engine import environment
from heat.engine import resource as res
from heat.engine import service
from heat.tests import common
from heat.tests import utils


class ResourceTypeTest(common.HeatTestCase):

    def setUp(self):
        super(ResourceTypeTest, self).setUp()
        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types(self, mock_is_service_available):
        mock_is_service_available.return_value = True
        resources = self.eng.list_resource_types(self.ctx)
        self.assertIsInstance(resources, list)
        self.assertIn('AWS::EC2::Instance', resources)
        self.assertIn('AWS::RDS::DBInstance', resources)

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types_deprecated(self,
                                            mock_is_service_available):
        mock_is_service_available.return_value = True
        resources = self.eng.list_resource_types(self.ctx, "DEPRECATED")
        self.assertEqual(set(['OS::Heat::HARestarter',
                              'OS::Heat::SoftwareDeployments',
                              'OS::Heat::StructuredDeployments']),
                         set(resources))

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types_supported(self,
                                           mock_is_service_available):
        mock_is_service_available.return_value = True
        resources = self.eng.list_resource_types(self.ctx, "SUPPORTED")
        self.assertNotIn(['OS::Neutron::RouterGateway'], resources)
        self.assertIn('AWS::EC2::Instance', resources)

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types_unavailable(
            self,
            mock_is_service_available):
        mock_is_service_available.return_value = False
        resources = self.eng.list_resource_types(self.ctx)
        # Check for an known resource, not listed
        self.assertNotIn('OS::Nova::Server', resources)

    def test_resource_schema(self):
        type_name = 'ResourceWithPropsType'
        expected = {
            'resource_type': type_name,
            'properties': {
                'Foo': {
                    'type': 'string',
                    'required': False,
                    'update_allowed': False,
                    'immutable': False,
                },
                'FooInt': {
                    'type': 'integer',
                    'required': False,
                    'update_allowed': False,
                    'immutable': False,
                },
            },
            'attributes': {
                'foo': {'description': 'A generic attribute'},
                'Foo': {'description': 'Another generic attribute'},
                'show': {
                    'description': 'Dictionary with resource attributes.',
                    'type': 'map'},
            },
            'support_status': {
                'status': 'SUPPORTED',
                'version': None,
                'message': None,
                'previous_status': None
            },
        }

        schema = self.eng.resource_schema(self.ctx, type_name=type_name)
        self.assertEqual(expected, schema)

    def test_resource_schema_with_attr_type(self):

        type_name = 'ResourceWithAttributeType'
        expected = {
            'resource_type': type_name,
            'properties': {},
            'attributes': {
                'attr1': {'description': 'A generic attribute',
                          'type': 'string'},
                'attr2': {'description': 'Another generic attribute',
                          'type': 'map'},
                'show': {
                    'description': 'Dictionary with resource attributes.',
                    'type': 'map'},
            },
            'support_status': {
                'status': 'SUPPORTED',
                'version': None,
                'message': None,
                'previous_status': None
            },
        }
        schema = self.eng.resource_schema(self.ctx, type_name=type_name)
        self.assertEqual(expected, schema)

    def _no_template_file(self, function):
        env = environment.Environment()
        info = environment.ResourceInfo(env.registry,
                                        ['ResourceWithWrongRefOnFile'],
                                        'not_existing.yaml')
        mock_iterable = mock.MagicMock(return_value=iter([info]))
        with mock.patch('heat.engine.environment.ResourceRegistry.iterable_by',
                        new=mock_iterable):
            ex = self.assertRaises(exception.TemplateNotFound,
                                   function,
                                   self.ctx,
                                   type_name='ResourceWithWrongRefOnFile')
            msg = 'Could not fetch remote template "not_existing.yaml"'
            self.assertIn(msg, six.text_type(ex))

    def test_resource_schema_no_template_file(self):
        self._no_template_file(self.eng.resource_schema)

    def test_generate_template_no_template_file(self):
        self._no_template_file(self.eng.generate_template)

    def test_resource_schema_nonexist(self):
        ex = self.assertRaises(exception.ResourceTypeNotFound,
                               self.eng.resource_schema,
                               self.ctx, type_name='Bogus')
        msg = 'The Resource Type (Bogus) could not be found.'
        self.assertEqual(msg, six.text_type(ex))
