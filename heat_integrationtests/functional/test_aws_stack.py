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

import hashlib
import json
import random

from six.moves.urllib import parse
from swiftclient import utils as swiftclient_utils
import yaml

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base


class AwsStackTest(functional_base.FunctionalTestsBase):
    test_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  the_nested:
    Type: AWS::CloudFormation::Stack
    Properties:
      TemplateURL: the.yaml
      Parameters:
        KeyName: foo
Outputs:
  output_foo:
    Value: {"Fn::GetAtt": [the_nested, Outputs.Foo]}
'''

    nested_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Outputs:
  Foo:
    Value: bar
'''

    update_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Outputs:
  Foo:
    Value: foo
'''

    nested_with_res_template = '''
HeatTemplateFormatVersion: '2012-12-12'
Parameters:
  KeyName:
    Type: String
Resources:
  NestedResource:
    Type: OS::Heat::RandomString
Outputs:
  Foo:
    Value: {"Fn::GetAtt": [NestedResource, value]}
'''

    def setUp(self):
        super(AwsStackTest, self).setUp()
        if not self.is_service_available('object-store'):
            self.skipTest('object-store service not available, skipping')
        self.object_container_name = test.rand_name()
        self.project_id = self.identity_client.project_id
        self.swift_key = hashlib.sha224(
            str(random.getrandbits(256)).encode('ascii')).hexdigest()[:32]
        key_header = 'x-container-meta-temp-url-key'
        self.object_client.put_container(self.object_container_name,
                                         {key_header: self.swift_key})
        self.addCleanup(self.object_client.delete_container,
                        self.object_container_name)

    def publish_template(self, contents, cleanup=True):
        oc = self.object_client

        # post the object
        oc.put_object(self.object_container_name, 'template.yaml', contents)
        if cleanup:
            self.addCleanup(oc.delete_object,
                            self.object_container_name,
                            'template.yaml')
        path = '/v1/AUTH_%s/%s/%s' % (self.project_id,
                                      self.object_container_name,
                                      'template.yaml')
        timeout = self.conf.build_timeout * 10
        tempurl = swiftclient_utils.generate_temp_url(path, timeout,
                                                      self.swift_key, 'GET')
        sw_url = parse.urlparse(oc.url)
        return '%s://%s%s' % (sw_url.scheme, sw_url.netloc, tempurl)

    def test_nested_stack_create(self):
        url = self.publish_template(self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        stack_identifier = self.stack_create(template=self.template)
        stack = self.client.stacks.get(stack_identifier)
        self.assert_resource_is_a_stack(stack_identifier, 'the_nested')
        self.assertEqual('bar', self._stack_output(stack, 'output_foo'))

    def test_nested_stack_create_with_timeout(self):
        url = self.publish_template(self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        timeout_template = yaml.safe_load(self.template)
        props = timeout_template['Resources']['the_nested']['Properties']
        props['TimeoutInMinutes'] = '50'

        stack_identifier = self.stack_create(
            template=timeout_template)
        stack = self.client.stacks.get(stack_identifier)
        self.assert_resource_is_a_stack(stack_identifier, 'the_nested')
        self.assertEqual('bar', self._stack_output(stack, 'output_foo'))

    def test_nested_stack_adopt_ok(self):
        url = self.publish_template(self.nested_with_res_template)
        self.template = self.test_template.replace('the.yaml', url)
        adopt_data = {
            "resources": {
                "the_nested": {
                    "resource_id": "test-res-id",
                    "resources": {
                        "NestedResource": {
                            "type": "OS::Heat::RandomString",
                            "resource_id": "test-nested-res-id",
                            "resource_data": {"value": "goopie"}
                        }
                    }
                }
            },
            "environment": {"parameters": {}},
            "template": yaml.safe_load(self.template)
        }

        stack_identifier = self.stack_adopt(adopt_data=json.dumps(adopt_data))

        self.assert_resource_is_a_stack(stack_identifier, 'the_nested')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('goopie', self._stack_output(stack, 'output_foo'))

    def test_nested_stack_adopt_fail(self):
        url = self.publish_template(self.nested_with_res_template)
        self.template = self.test_template.replace('the.yaml', url)
        adopt_data = {
            "resources": {
                "the_nested": {
                    "resource_id": "test-res-id",
                    "resources": {
                    }
                }
            },
            "environment": {"parameters": {}},
            "template": yaml.safe_load(self.template)
        }

        stack_identifier = self.stack_adopt(adopt_data=json.dumps(adopt_data),
                                            wait_for_status='ADOPT_FAILED')
        rsrc = self.client.resources.get(stack_identifier, 'the_nested')
        self.assertEqual('ADOPT_FAILED', rsrc.resource_status)

    def test_nested_stack_update(self):
        url = self.publish_template(self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        stack_identifier = self.stack_create(template=self.template)
        original_nested_id = self.assert_resource_is_a_stack(
            stack_identifier, 'the_nested')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('bar', self._stack_output(stack, 'output_foo'))

        new_template = yaml.safe_load(self.template)
        props = new_template['Resources']['the_nested']['Properties']
        props['TemplateURL'] = self.publish_template(self.update_template,
                                                     cleanup=False)

        self.update_stack(stack_identifier, new_template)

        # Expect the physical resource name staying the same after update,
        # so that the nested was actually updated instead of replaced.
        new_nested_id = self.assert_resource_is_a_stack(
            stack_identifier, 'the_nested')
        self.assertEqual(original_nested_id, new_nested_id)
        updt_stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('foo', self._stack_output(updt_stack, 'output_foo'))

    def test_nested_stack_suspend_resume(self):
        url = self.publish_template(self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        stack_identifier = self.stack_create(template=self.template)
        self.stack_suspend(stack_identifier)
        self.stack_resume(stack_identifier)
