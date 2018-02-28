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


class TemplateVersionTest(functional_base.FunctionalTestsBase):
    """This will test list template versions"""

    def test_template_version(self):
        template_versions = self.client.template_versions.list()
        supported_template_versions = ["2013-05-23", "2014-10-16",
                                       "2015-04-30", "2015-10-15",
                                       "2012-12-12", "2010-09-09",
                                       "2016-04-08", "2016-10-14", "newton",
                                       "2017-02-24", "ocata",
                                       "2017-09-01", "pike",
                                       "2018-03-02", "queens",
                                       "2018-08-31", "rocky"]
        for template in template_versions:
            self.assertIn(template.version.split(".")[1],
                          supported_template_versions)
