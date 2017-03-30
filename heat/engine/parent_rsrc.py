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

import weakref

from heat.objects import resource as resource_object


class ParentResourceProxy(object):
    """Proxy for the TemplateResource that owns a provider stack.

    This is an interface through which the Fn::ResourceFacade/resource_facade
    intrinsic functions in a stack can access data about the TemplateResource
    in the parent stack for which it was created.

    This API can be considered stable by third-party Function plugins, and no
    part of it should be changed or removed without an appropriate deprecation
    process.
    """

    def __new__(cls, context, parent_resource_name, parent_stack_id):
        if parent_resource_name is None:
            return None
        return super(ParentResourceProxy, cls).__new__(cls)

    def __init__(self, context, parent_resource_name, parent_stack_id):
        self._context = context
        self.name = parent_resource_name
        self._stack_id = parent_stack_id
        self._stack_ref = None
        self._parent_stack = None

    def _stack(self):
        if self._stack_ref is not None:
            stk = self._stack_ref()
            if stk is not None:
                return stk

        assert self._stack_id is not None, "Must provide parent stack or ID"

        from heat.engine import stack
        self._parent_stack = stack.Stack.load(self._context,
                                              stack_id=self._stack_id)
        self._stack_ref = weakref.ref(self._parent_stack)
        return self._parent_stack

    def metadata_get(self):
        """Return the resource metadata."""
        # If we're using an existing stack that was passed in, assume that its
        # resources are already in memory. If they haven't been stored to the
        # DB yet, this avoids an unnecessary attempt to read from it.
        if self._parent_stack is None:
            refd_stk = self._stack_ref and self._stack_ref()
            if refd_stk is not None:
                return refd_stk[self.name].metadata_get()

        assert self._stack_id is not None, "Must provide parent stack or ID"

        # Try to read just this resource from the DB
        rs = resource_object.Resource.get_by_name_and_stack(self._context,
                                                            self.name,
                                                            self._stack_id)
        if rs is not None:
            return rs.rsrc_metadata

        # Resource not stored, just return the data from the template
        return self.t.metadata()

    @property
    def t(self):
        """The resource definition."""
        stk = self._stack()
        return stk.t.resource_definitions(stk)[self.name]


def use_parent_stack(parent_proxy, stack):
    parent_proxy._stack_ref = weakref.ref(stack)
    parent_proxy._parent_stack = None
