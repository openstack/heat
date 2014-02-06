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

import itertools

from heat.common import short_id
from heat.scaling import template
from heat.tests.common import HeatTestCase


class ResourceTemplatesTest(HeatTestCase):

    def setUp(self):
        super(ResourceTemplatesTest, self).setUp()
        ids = ('stubbed-id-%s' % (i,) for i in itertools.count())
        self.patchobject(short_id, 'generate_id').side_effect = ids.next

    def test_create_template(self):
        """
        When creating a template from scratch, an empty list is accepted as
        the "old" resources and new resources are created up to num_resource.
        """
        templates = template.resource_templates([], {'type': 'Foo'}, 2, 0)
        expected = [
            ('stubbed-id-0', {'type': 'Foo'}),
            ('stubbed-id-1', {'type': 'Foo'})]
        self.assertEqual(expected, list(templates))

    def test_replace_template(self):
        """
        If num_replace is the number of old resources, then all of the
        resources will be replaced.
        """
        old_resources = [
            ('old-id-0', {'type': 'Foo'}),
            ('old-id-1', {'type': 'Foo'})]
        templates = template.resource_templates(old_resources, {'type': 'Bar'},
                                                1, 2)
        expected = [('old-id-1', {'type': 'Bar'})]
        self.assertEqual(expected, list(templates))

    def test_replace_some_units(self):
        """
        If the resource definition changes, only the number of replacements
        specified will be made; beyond that, the original templates are used.
        """
        old_resources = [
            ('old-id-0', {'type': 'Foo'}),
            ('old-id-1', {'type': 'Foo'})]
        new_spec = {'type': 'Bar'}
        templates = template.resource_templates(old_resources, new_spec, 2, 1)
        expected = [
            ('old-id-0', {'type': 'Bar'}),
            ('old-id-1', {'type': 'Foo'})]
        self.assertEqual(expected, list(templates))

    def test_growth_counts_as_replacement(self):
        """
        If we grow the template and replace some elements at the same time, the
        number of replacements to perform is reduced by the number of new
        resources to be created.
        """
        spec = {'type': 'Foo'}
        old_resources = [
            ('old-id-0', spec),
            ('old-id-1', spec)]
        new_spec = {'type': 'Bar'}
        templates = template.resource_templates(old_resources, new_spec, 4, 2)
        expected = [
            ('old-id-0', spec),
            ('old-id-1', spec),
            ('stubbed-id-0', new_spec),
            ('stubbed-id-1', new_spec)]
        self.assertEqual(expected, list(templates))

    def test_replace_units_some_already_up_to_date(self):
        """
        If some of the old resources already have the new resource definition,
        then they won't be considered for replacement, and the next resource
        that is out-of-date will be replaced.
        """
        old_resources = [
            ('old-id-0', {'type': 'Bar'}),
            ('old-id-1', {'type': 'Foo'})]
        new_spec = {'type': 'Bar'}
        templates = template.resource_templates(old_resources, new_spec, 2, 1)
        second_batch_expected = [
            ('old-id-0', {'type': 'Bar'}),
            ('old-id-1', {'type': 'Bar'})]
        self.assertEqual(second_batch_expected, list(templates))
