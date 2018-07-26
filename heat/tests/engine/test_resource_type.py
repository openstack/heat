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
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


class ResourceTypeTest(common.HeatTestCase):

    def setUp(self):
        super(ResourceTypeTest, self).setUp()
        self.ctx = utils.dummy_context(tenant_id='stack_service_test_tenant')
        self.eng = service.EngineService('a-host', 'a-topic')

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types(self, mock_is_service_available):
        mock_is_service_available.return_value = (True, None)
        resources = self.eng.list_resource_types(self.ctx)
        self.assertIsInstance(resources, list)
        self.assertIn('AWS::EC2::Instance', resources)
        self.assertIn('AWS::RDS::DBInstance', resources)

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types_deprecated(self,
                                            mock_is_service_available):
        mock_is_service_available.return_value = (True, None)
        resources = self.eng.list_resource_types(self.ctx, "DEPRECATED")
        self.assertEqual(set(['OS::Aodh::Alarm',
                              'OS::Glance::Image']),
                         set(resources))

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types_supported(self,
                                           mock_is_service_available):
        mock_is_service_available.return_value = (True, None)
        resources = self.eng.list_resource_types(self.ctx, "SUPPORTED")
        self.assertNotIn(['OS::Neutron::RouterGateway'], resources)
        self.assertIn('AWS::EC2::Instance', resources)

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types_unavailable(
            self,
            mock_is_service_available):
        mock_is_service_available.return_value = (
            False, 'Service endpoint not in service catalog.')
        resources = self.eng.list_resource_types(self.ctx)
        # Check for a known resource, not listed
        self.assertNotIn('OS::Nova::Server', resources)

    @mock.patch.object(res.Resource, 'is_service_available')
    def test_list_resource_types_with_descr(self, mock_is_service_available):
        mock_is_service_available.return_value = (True, None)
        resources = self.eng.list_resource_types(self.ctx,
                                                 with_description=True)
        self.assertIsInstance(resources, list)
        self.assertIn({'resource_type': 'AWS::RDS::DBInstance',
                       'description': 'Builtin AWS::RDS::DBInstance'},
                      resources)
        self.assertIn({'resource_type': 'AWS::EC2::Instance',
                       'description': 'No description available'},
                      resources)

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
                    'description': 'Detailed information about resource.',
                    'type': 'map'},
            },
            'support_status': {
                'status': 'SUPPORTED',
                'version': None,
                'message': None,
                'previous_status': None
            },
            'description': 'No description available'
        }

        schema = self.eng.resource_schema(self.ctx, type_name=type_name,
                                          with_description=True)
        self.assertEqual(expected, schema)

    def test_resource_schema_for_hidden_type(self):
        type_name = 'ResourceTypeHidden'
        self.assertRaises(exception.NotSupported, self.eng.resource_schema,
                          self.ctx, type_name)

    def test_generate_template_for_hidden_type(self):
        type_name = 'ResourceTypeHidden'
        self.assertRaises(exception.NotSupported, self.eng.generate_template,
                          self.ctx, type_name)

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
                    'description': 'Detailed information about resource.',
                    'type': 'map'},
            },
            'support_status': {
                'status': 'SUPPORTED',
                'version': None,
                'message': None,
                'previous_status': None
            }
        }
        schema = self.eng.resource_schema(self.ctx, type_name=type_name)
        self.assertEqual(expected, schema)

    def test_resource_schema_with_hidden(self):

        type_name = 'ResourceWithHiddenPropertyAndAttribute'
        expected = {
            'resource_type': type_name,
            'properties': {
                'supported': {
                    'description': "Supported property.",
                    'type': 'list',
                    'immutable': False,
                    'required': False,
                    'update_allowed': False
                }
            },
            'attributes': {
                'supported': {'description': 'Supported attribute.',
                              'type': 'string'},
                'show': {
                    'description': 'Detailed information about resource.',
                    'type': 'map'},
            },
            'support_status': {
                'status': 'SUPPORTED',
                'version': None,
                'message': None,
                'previous_status': None
            }
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
            ex = self.assertRaises(exception.InvalidGlobalResource,
                                   function,
                                   self.ctx,
                                   type_name='ResourceWithWrongRefOnFile')
            msg = ('There was an error loading the definition of the global '
                   'resource type ResourceWithWrongRefOnFile.')
            self.assertIn(msg, six.text_type(ex))

    def test_resource_schema_no_template_file(self):
        self._no_template_file(self.eng.resource_schema)

    def test_generate_template_no_template_file(self):
        self._no_template_file(self.eng.generate_template)

    def test_resource_schema_nonexist(self):
        ex = self.assertRaises(exception.EntityNotFound,
                               self.eng.resource_schema,
                               self.ctx, type_name='Bogus')
        msg = 'The Resource Type (Bogus) could not be found.'
        self.assertEqual(msg, six.text_type(ex))

    def test_resource_schema_unavailable(self):
        type_name = 'ResourceWithDefaultClientName'

        with mock.patch.object(
                generic_rsrc.ResourceWithDefaultClientName,
                'is_service_available') as mock_is_service_available:
            mock_is_service_available.return_value = (
                False, 'Service endpoint not in service catalog.')
            ex = self.assertRaises(exception.ResourceTypeUnavailable,
                                   self.eng.resource_schema,
                                   self.ctx,
                                   type_name)
            msg = ('HEAT-E99001 Service sample is not available for resource '
                   'type ResourceWithDefaultClientName, reason: '
                   'Service endpoint not in service catalog.')
            self.assertEqual(msg,
                             six.text_type(ex),
                             'invalid exception message')

            mock_is_service_available.assert_called_once_with(self.ctx)
