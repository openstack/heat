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


class LifecyclePlugin(object):
    """Base class for pre-op and post-op work on a stack.

    Implementations should extend this class and override the methods.
    """
    def do_pre_op(self, cnxt, stack, current_stack=None, action=None):
        """Method to be run by heat before stack operations."""
        pass

    def do_post_op(self, cnxt, stack, current_stack=None, action=None,
                   is_stack_failure=False):
        """Method to be run by heat after stack operations, including failures.

        On failure to execute all the registered pre_ops, this method will be
        called if and only if the corresponding pre_op was successfully called.
        On failures of the actual stack operation, this method will
        be called if all the pre operations were successfully called.
        """
        pass

    def get_ordinal(self):
        """Get the sort order for pre and post operation execution.

        The values returned by get_ordinal are used to create a partial order
        for pre and post operation method invocations. The default ordinal
        value of 100 may be overridden.
        If class1inst.ordinal() < class2inst.ordinal(), then the method on
        class1inst will be executed before the method on class2inst.
        If class1inst.ordinal() > class2inst.ordinal(), then the method on
        class1inst will be executed after the method on class2inst.
        If class1inst.ordinal() == class2inst.ordinal(), then the order of
        method invocation is indeterminate.
        """
        return 100
