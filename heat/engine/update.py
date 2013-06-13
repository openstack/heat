# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.engine import resource
from heat.engine import scheduler

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class StackUpdate(object):
    """
    A Task to perform the update of an existing stack to a new template.
    """

    def __init__(self, existing_stack, new_stack):
        """Initialise with the existing stack and the new stack."""
        self.existing_stack = existing_stack
        self.new_stack = new_stack

        self.existing_snippets = dict((r.name, r.parsed_template())
                                      for r in self.existing_stack)

    def __str__(self):
        return '%s Update' % str(self.existing_stack)

    @scheduler.wrappertask
    def __call__(self):
        """Return a co-routine that updates the stack."""

        existing_deps = self.existing_stack.dependencies
        new_deps = self.new_stack.dependencies

        cleanup = scheduler.DependencyTaskGroup(existing_deps,
                                                self._remove_old_resource,
                                                reverse=True)
        create_new = scheduler.DependencyTaskGroup(new_deps,
                                                   self._create_new_resource)
        update = scheduler.DependencyTaskGroup(new_deps,
                                               self._update_resource)

        yield cleanup()
        yield create_new()
        yield update()

    @scheduler.wrappertask
    def _remove_old_resource(self, existing_res):
        res_name = existing_res.name
        if res_name not in self.new_stack:
            logger.debug("resource %s not found in updated stack"
                         % res_name + " definition, deleting")
            yield existing_res.destroy()
            del self.existing_stack.resources[res_name]

    @scheduler.wrappertask
    def _create_new_resource(self, new_res):
        res_name = new_res.name
        if res_name not in self.existing_stack:
            logger.debug("resource %s not found in current stack"
                         % res_name + " definition, adding")
            new_res.stack = self.existing_stack
            self.existing_stack[res_name] = new_res
            yield new_res.create()

    @scheduler.wrappertask
    def _replace_resource(self, new_res):
        res_name = new_res.name
        yield self.existing_stack[res_name].destroy()
        new_res.stack = self.existing_stack
        self.existing_stack[res_name] = new_res
        yield new_res.create()

    @scheduler.wrappertask
    def _update_resource(self, new_res):
        res_name = new_res.name

        if res_name not in self.existing_snippets:
            return

        # Compare resolved pre/post update resource snippets,
        # note the new resource snippet is resolved in the context
        # of the existing stack (which is the stack being updated)
        existing_snippet = self.existing_snippets[res_name]
        new_snippet = self.existing_stack.resolve_runtime_data(new_res.t)

        if new_snippet != existing_snippet:
            try:
                yield self.existing_stack[res_name].update(new_snippet,
                                                           existing_snippet)
            except resource.UpdateReplace:
                yield self._replace_resource(new_res)
            else:
                logger.info("Resource %s for stack %s updated" %
                            (res_name, self.existing_stack.name))
