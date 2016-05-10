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


from heat_integrationtests.functional import functional_base


class TemplateAPITest(functional_base.FunctionalTestsBase):
    """This will test the following template calls:

    1. Get the template content for the specific stack
    2. List template versions
    3. List resource types
    4. Show resource details for OS::Heat::TestResource
    """

    template = {
        'heat_template_version': '2014-10-16',
        'description': 'Test Template APIs',
        'resources': {
            'test1': {
                'type': 'OS::Heat::TestResource',
                'properties': {
                    'update_replace': False,
                    'wait_secs': 0,
                    'value': 'Test1',
                    'fail': False,
                }
            }
        }
    }

    def setUp(self):
        super(TemplateAPITest, self).setUp()

    def test_get_stack_template(self):
        stack_identifier = self.stack_create(
            template=self.template
        )
        template_from_client = self.client.stacks.template(stack_identifier)
        self.assertDictEqual(self.template, template_from_client)

    def test_template_version(self):
        template_versions = self.client.template_versions.list()
        supported_template_versions = ["2013-05-23", "2014-10-16",
                                       "2015-04-30", "2015-10-15",
                                       "2012-12-12", "2010-09-09",
                                       "2016-04-08", "2016-10-14", "newton"]
        for template in template_versions:
            self.assertIn(template.version.split(".")[1],
                          supported_template_versions)

    def test_resource_types(self):
        resource_types = self.client.resource_types.list()
        self.assertTrue(any(resource.resource_type == "OS::Heat::TestResource"
                            for resource in resource_types))

    def test_show_resource_template(self):
        resource_details = self.client.resource_types.get(
            resource_type="OS::Heat::TestResource"
        )
        self.assertEqual("OS::Heat::TestResource",
                         resource_details['resource_type'])
