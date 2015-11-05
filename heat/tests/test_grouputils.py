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

from heat.common import grouputils
from heat.common import template_format
from heat.engine import rsrc_defn
from heat.tests import common
from heat.tests import utils

nested_stack = '''
heat_template_version: 2013-05-23
resources:
  r0:
    type: OverwrittenFnGetRefIdType
  r1:
    type: OverwrittenFnGetRefIdType
'''


class GroupUtilsTest(common.HeatTestCase):

    def test_non_nested_resource(self):
        group = mock.Mock()
        self.patchobject(group, 'nested', return_value=None)

        self.assertEqual(0, grouputils.get_size(group))
        self.assertEqual([], grouputils.get_members(group))
        self.assertEqual([], grouputils.get_member_refids(group))
        self.assertEqual([], grouputils.get_member_names(group))

    def test_normal_group(self):
        group = mock.Mock()
        t = template_format.parse(nested_stack)
        stack = utils.parse_stack(t)
        # group size
        self.patchobject(group, 'nested', return_value=stack)
        self.assertEqual(2, grouputils.get_size(group))

        # member list (sorted)
        members = [r for r in six.itervalues(stack)]
        expected = sorted(members, key=lambda r: (r.created_time, r.name))
        actual = grouputils.get_members(group)
        self.assertEqual(expected, actual)

        # refids
        actual_ids = grouputils.get_member_refids(group)
        self.assertEqual(['ID-r0', 'ID-r1'], actual_ids)
        partial_ids = grouputils.get_member_refids(group, exclude=['ID-r1'])
        self.assertEqual(['ID-r0'], partial_ids)

        # names
        names = grouputils.get_member_names(group)
        self.assertEqual(['r0', 'r1'], names)

        # defn snippets as list
        expected = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType")

        member_defs = grouputils.get_member_definitions(group)
        self.assertEqual([(x, expected) for x in names], member_defs)

    def test_group_with_failed_members(self):
        group = mock.Mock()
        t = template_format.parse(nested_stack)
        stack = utils.parse_stack(t)
        self.patchobject(group, 'nested', return_value=stack)

        # Just failed for whatever reason
        rsrc_err = stack.resources['r0']
        rsrc_err.status = rsrc_err.FAILED
        rsrc_ok = stack.resources['r1']

        self.assertEqual(1, grouputils.get_size(group))
        self.assertEqual([rsrc_ok], grouputils.get_members(group))
        self.assertEqual(['ID-r1'], grouputils.get_member_refids(group))
        self.assertEqual(['r1'], grouputils.get_member_names(group))
