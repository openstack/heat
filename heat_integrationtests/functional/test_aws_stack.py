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

from oslo_log import log as logging
import requests
from six.moves.urllib import parse
from swiftclient import utils as swiftclient_utils
import yaml

from heat_integrationtests.common import test
from heat_integrationtests.functional import functional_base

LOG = logging.getLogger(__name__)


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
        self.object_container_name = AwsStackTest.__name__
        self.project_id = self.identity_client.auth_ref.project_id
        self.object_client.put_container(self.object_container_name)
        self.nested_name = '%s.yaml' % test.rand_name()

    def publish_template(self, name, contents):
        oc = self.object_client

        # post the object
        oc.put_object(self.object_container_name, name, contents)
        # TODO(asalkeld) see if this is causing problems.
        # self.addCleanup(self.object_client.delete_object,
        #                self.object_container_name, name)

        # make the tempurl
        key_header = 'x-account-meta-temp-url-key'
        if key_header not in oc.head_account():
            swift_key = hashlib.sha224(
                str(random.getrandbits(256))).hexdigest()[:32]
            LOG.warn('setting swift key to %s' % swift_key)
            oc.post_account({key_header: swift_key})
        key = oc.head_account()[key_header]
        path = '/v1/AUTH_%s/%s/%s' % (self.project_id,
                                      self.object_container_name, name)
        timeout = self.conf.build_timeout * 10
        tempurl = swiftclient_utils.generate_temp_url(path, timeout,
                                                      key, 'GET')
        sw_url = parse.urlparse(oc.url)
        full_url = '%s://%s%s' % (sw_url.scheme, sw_url.netloc, tempurl)

        def download():
            r = requests.get(full_url)
            LOG.info('GET: %s -> %s' % (full_url, r.status_code))
            return r.status_code == requests.codes.ok

        # make sure that the object is available.
        test.call_until_true(self.conf.build_timeout,
                             self.conf.build_interval, download)

        return full_url

    def test_nested_stack_create(self):
        url = self.publish_template(self.nested_name, self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        stack_identifier = self.stack_create(template=self.template)
        stack = self.client.stacks.get(stack_identifier)
        self.assert_resource_is_a_stack(stack_identifier, 'the_nested')
        self.assertEqual('bar', self._stack_output(stack, 'output_foo'))

    def test_nested_stack_create_with_timeout(self):
        url = self.publish_template(self.nested_name, self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        timeout_template = yaml.load(self.template)
        props = timeout_template['Resources']['the_nested']['Properties']
        props['TimeoutInMinutes'] = '50'

        stack_identifier = self.stack_create(
            template=timeout_template)
        stack = self.client.stacks.get(stack_identifier)
        self.assert_resource_is_a_stack(stack_identifier, 'the_nested')
        self.assertEqual('bar', self._stack_output(stack, 'output_foo'))

    def test_nested_stack_adopt_ok(self):
        url = self.publish_template(self.nested_name,
                                    self.nested_with_res_template)
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
            "template": yaml.load(self.template)
        }

        stack_identifier = self.stack_adopt(adopt_data=json.dumps(adopt_data))

        self.assert_resource_is_a_stack(stack_identifier, 'the_nested')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('goopie', self._stack_output(stack, 'output_foo'))

    def test_nested_stack_adopt_fail(self):
        url = self.publish_template(self.nested_name,
                                    self.nested_with_res_template)
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
            "template": yaml.load(self.template)
        }

        stack_identifier = self.stack_adopt(adopt_data=json.dumps(adopt_data),
                                            wait_for_status='ADOPT_FAILED')
        rsrc = self.client.resources.get(stack_identifier, 'the_nested')
        self.assertEqual('ADOPT_FAILED', rsrc.resource_status)

    def test_nested_stack_update(self):
        url = self.publish_template(self.nested_name, self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        stack_identifier = self.stack_create(template=self.template)
        original_nested_id = self.assert_resource_is_a_stack(
            stack_identifier, 'the_nested')
        stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('bar', self._stack_output(stack, 'output_foo'))

        new_template = yaml.load(self.template)
        props = new_template['Resources']['the_nested']['Properties']
        props['TemplateURL'] = self.publish_template(self.nested_name,
                                                     self.update_template)

        self.update_stack(stack_identifier, new_template)

        # Expect the physical resource name staying the same after update,
        # so that the nested was actually updated instead of replaced.
        new_nested_id = self.assert_resource_is_a_stack(
            stack_identifier, 'the_nested')
        self.assertEqual(original_nested_id, new_nested_id)
        updt_stack = self.client.stacks.get(stack_identifier)
        self.assertEqual('foo', self._stack_output(updt_stack, 'output_foo'))

    def test_nested_stack_suspend_resume(self):
        url = self.publish_template(self.nested_name, self.nested_template)
        self.template = self.test_template.replace('the.yaml', url)
        stack_identifier = self.stack_create(template=self.template)
        self.stack_suspend(stack_identifier)
        self.stack_resume(stack_identifier)
