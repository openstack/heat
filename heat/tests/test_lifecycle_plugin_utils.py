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

from heat.common import lifecycle_plugin_utils
from heat.engine import lifecycle_plugin
from heat.engine import resources
from heat.tests import common


empty_template = '''
heat_template_version: '2013-05-23'
description: Empty stack
resources:
'''


class LifecyclePluginUtilsTest(common.HeatTestCase):
    """Basic tests for :module:'heat.common.lifecycle_plugin_utils'.

    Basic tests for the helper methods in
    :module:'heat.common.lifecycle_plugin_utils'.
    """

    def tearDown(self):
        super(LifecyclePluginUtilsTest, self).tearDown()
        lifecycle_plugin_utils.pp_class_instances = None

    def mock_lcp_class_map(self, lcp_mappings):
        self.mock_get_plugins = self.patchobject(
            resources.global_env(), 'get_stack_lifecycle_plugins',
            return_value=lcp_mappings)
        # reset cache
        lifecycle_plugin_utils.pp_class_instances = None

    def test_get_plug_point_class_instances(self):
        """Tests the get_plug_point_class_instances function."""
        lcp_mappings = [('A::B::C1', TestLifecycleCallout1)]
        self.mock_lcp_class_map(lcp_mappings)

        pp_cinstances = lifecycle_plugin_utils.get_plug_point_class_instances()
        self.assertIsNotNone(pp_cinstances)
        self.assertTrue(self.is_iterable(pp_cinstances),
                        "not iterable: %s" % pp_cinstances)
        self.assertEqual(1, len(pp_cinstances))
        self.assertEqual(TestLifecycleCallout1, pp_cinstances[0].__class__)
        self.mock_get_plugins.assert_called_once_with()

    def test_do_pre_and_post_callouts(self):
        lcp_mappings = [('A::B::C1', TestLifecycleCallout1)]
        self.mock_lcp_class_map(lcp_mappings)
        mc = mock.Mock()
        mc.__setattr__("pre_counter_for_unit_test", 0)
        mc.__setattr__("post_counter_for_unit_test", 0)
        ms = mock.Mock()
        ms.__setattr__("action", 'A')
        lifecycle_plugin_utils.do_pre_ops(mc, ms, None, None)
        self.assertEqual(1, mc.pre_counter_for_unit_test)
        lifecycle_plugin_utils.do_post_ops(mc, ms, None, None)
        self.assertEqual(1, mc.post_counter_for_unit_test)
        self.mock_get_plugins.assert_called_once_with()

    def test_class_instantiation_and_sorting(self):
        lcp_mappings = []
        self.mock_lcp_class_map(lcp_mappings)
        pp_cis = lifecycle_plugin_utils.get_plug_point_class_instances()
        self.assertEqual(0, len(pp_cis))
        self.mock_get_plugins.assert_called_once_with()

        # order should change with sort
        lcp_mappings = [('A::B::C2', TestLifecycleCallout2),
                        ('A::B::C1', TestLifecycleCallout1)]
        self.mock_lcp_class_map(lcp_mappings)
        pp_cis = lifecycle_plugin_utils.get_plug_point_class_instances()
        self.assertEqual(2, len(pp_cis))
        self.assertEqual(100, pp_cis[0].get_ordinal())
        self.assertEqual(101, pp_cis[1].get_ordinal())
        self.assertEqual(TestLifecycleCallout1, pp_cis[0].__class__)
        self.assertEqual(TestLifecycleCallout2, pp_cis[1].__class__)
        self.mock_get_plugins.assert_called_once_with()

        # order should NOT change with sort
        lcp_mappings = [('A::B::C1', TestLifecycleCallout1),
                        ('A::B::C2', TestLifecycleCallout2)]
        self.mock_lcp_class_map(lcp_mappings)
        pp_cis = lifecycle_plugin_utils.get_plug_point_class_instances()
        self.assertEqual(2, len(pp_cis))
        self.assertEqual(100, pp_cis[0].get_ordinal())
        self.assertEqual(101, pp_cis[1].get_ordinal())
        self.assertEqual(TestLifecycleCallout1, pp_cis[0].__class__)
        self.assertEqual(TestLifecycleCallout2, pp_cis[1].__class__)
        self.mock_get_plugins.assert_called_once_with()

        # sort failure due to exception in thrown by ordinal
        lcp_mappings = [('A::B::C2', TestLifecycleCallout2),
                        ('A::B::C3', TestLifecycleCallout3),
                        ('A::B::C1', TestLifecycleCallout1)]
        self.mock_lcp_class_map(lcp_mappings)
        pp_cis = lifecycle_plugin_utils.get_plug_point_class_instances()
        self.assertEqual(3, len(pp_cis))
        self.assertEqual(100, pp_cis[2].get_ordinal())
        self.assertEqual(101, pp_cis[0].get_ordinal())
        # (can sort fail partially? If so then this test may break)
        self.assertEqual(TestLifecycleCallout2, pp_cis[0].__class__)
        self.assertEqual(TestLifecycleCallout3, pp_cis[1].__class__)
        self.assertEqual(TestLifecycleCallout1, pp_cis[2].__class__)
        self.mock_get_plugins.assert_called_once_with()

    def test_do_pre_op_failure(self):
        lcp_mappings = [('A::B::C5', TestLifecycleCallout1),
                        ('A::B::C4', TestLifecycleCallout4)]
        self.mock_lcp_class_map(lcp_mappings)
        mc = mock.Mock()
        mc.__setattr__("pre_counter_for_unit_test", 0)
        mc.__setattr__("post_counter_for_unit_test", 0)
        ms = mock.Mock()
        ms.__setattr__("action", 'A')
        failed = False
        try:
            lifecycle_plugin_utils.do_pre_ops(mc, ms, None, None)
        except Exception:
            failed = True
        self.assertTrue(failed)
        self.assertEqual(1, mc.pre_counter_for_unit_test)
        self.assertEqual(1, mc.post_counter_for_unit_test)
        self.mock_get_plugins.assert_called_once_with()

    def test_do_post_op_failure(self):
        lcp_mappings = [('A::B::C1', TestLifecycleCallout1),
                        ('A::B::C5', TestLifecycleCallout5)]
        self.mock_lcp_class_map(lcp_mappings)
        mc = mock.Mock()
        mc.__setattr__("pre_counter_for_unit_test", 0)
        mc.__setattr__("post_counter_for_unit_test", 0)
        ms = mock.Mock()
        ms.__setattr__("action", 'A')
        lifecycle_plugin_utils.do_post_ops(mc, ms, None, None)
        self.assertEqual(1, mc.post_counter_for_unit_test)
        self.mock_get_plugins.assert_called_once_with()

    def test_exercise_base_lifecycle_plugin_class(self):
        lcp = lifecycle_plugin.LifecyclePlugin()
        ordinal = lcp.get_ordinal()
        lcp.do_pre_op(None, None, None)
        lcp.do_post_op(None, None, None)
        self.assertEqual(100, ordinal)

    def is_iterable(self, obj):
        # special case string
        if not object:
            return False
        if isinstance(obj, str):
            return False

        # Test for iterabilityy
        try:
            for m in obj:
                break
        except TypeError:
            return False
        return True


class TestLifecycleCallout1(lifecycle_plugin.LifecyclePlugin):
    """Sample test class for testing pre-op and post-op work on a stack."""

    def do_pre_op(self, cnxt, stack, current_stack=None, action=None):
        cnxt.pre_counter_for_unit_test += 1

    def do_post_op(self, cnxt, stack, current_stack=None, action=None,
                   is_stack_failure=False):
        cnxt.post_counter_for_unit_test += 1

    def get_ordinal(self):
        return 100


class TestLifecycleCallout2(lifecycle_plugin.LifecyclePlugin):
    """Sample test class for testing pre-op and post-op work on a stack.

    Different ordinal and increment counters by 2.
    """

    def do_pre_op(self, cnxt, stack, current_stack=None, action=None):
        cnxt.pre_counter_for_unit_test += 2

    def do_post_op(self, cnxt, stack, current_stack=None, action=None,
                   is_stack_failure=False):
        cnxt.post_counter_for_unit_test += 2

    def get_ordinal(self):
        return 101


class TestLifecycleCallout3(lifecycle_plugin.LifecyclePlugin):
    """Sample test class for testing pre-op and post-op work on a stack.

    Methods raise exceptions.
    """
    def do_pre_op(self, cnxt, stack, current_stack=None, action=None):
        raise Exception()

    def do_post_op(self, cnxt, stack, current_stack=None, action=None,
                   is_stack_failure=False):
        raise Exception()

    def get_ordinal(self):
        raise Exception()


class TestLifecycleCallout4(lifecycle_plugin.LifecyclePlugin):
    """Sample test class for testing pre-op and post-op work on a stack.

    do_pre_op, do_post_op both throw exception.
    """
    def do_pre_op(self, cnxt, stack, current_stack=None, action=None):
        raise Exception()

    def do_post_op(self, cnxt, stack, current_stack=None, action=None,
                   is_stack_failure=False):
        raise Exception()

    def get_ordinal(self):
        return 103


class TestLifecycleCallout5(lifecycle_plugin.LifecyclePlugin):
    """Sample test class for testing pre-op and post-op work on a stack.

    do_post_op throws exception.
    """
    def do_pre_op(self, cnxt, stack, current_stack=None, action=None):
        cnxt.pre_counter_for_unit_test += 1

    def do_post_op(self, cnxt, stack, current_stack=None, action=None,
                   is_stack_failure=False):
        raise Exception()

    def get_ordinal(self):
        return 100
