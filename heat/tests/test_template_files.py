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

from heat.engine import template_files
from heat.tests import common
from heat.tests import utils

template_files_1 = {'template file 1': 'Contents of template 1',
                    'template file 2': 'More template contents'}


class TestTemplateFiles(common.HeatTestCase):

    def test_cache_miss(self):
        ctx = utils.dummy_context()
        tf1 = template_files.TemplateFiles(template_files_1)
        tf1.store(ctx)
        # As this is the only reference to the value in _d, deleting
        # t1.files will cause the value to get removed from _d (due to
        # it being a WeakValueDictionary.
        del tf1.files
        self.assertNotIn(tf1.files_id, template_files._d)
        # this will cause the cache refresh
        self.assertEqual(template_files_1['template file 1'],
                         tf1['template file 1'])
        self.assertEqual(template_files_1, template_files._d[tf1.files_id])

    def test_d_weakref_behaviour(self):
        ctx = utils.dummy_context()
        tf1 = template_files.TemplateFiles(template_files_1)
        tf1.store(ctx)
        tf2 = template_files.TemplateFiles(tf1)
        del tf1.files
        self.assertIn(tf2.files_id, template_files._d)
        del tf2.files
        self.assertNotIn(tf2.files_id, template_files._d)
