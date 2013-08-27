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

from heat.db import api as db_api

from heat.engine import resource
from heat.engine import scheduler

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class StackUpdate(object):
    """
    A Task to perform the update of an existing stack to a new template.
    """

    def __init__(self, existing_stack, new_stack, previous_stack,
                 rollback=False):
        """Initialise with the existing stack and the new stack."""
        self.existing_stack = existing_stack
        self.new_stack = new_stack
        self.previous_stack = previous_stack

        self.rollback = rollback

        self.existing_snippets = dict((r.name, r.parsed_template())
                                      for r in self.existing_stack)

    def __repr__(self):
        if self.rollback:
            return '%s Rollback' % str(self.existing_stack)
        else:
            return '%s Update' % str(self.existing_stack)

    @scheduler.wrappertask
    def __call__(self):
        """Return a co-routine that updates the stack."""

        existing_deps = self.existing_stack.dependencies
        new_deps = self.new_stack.dependencies

        cleanup_prev = scheduler.DependencyTaskGroup(
            self.previous_stack.dependencies,
            self._remove_backup_resource,
            reverse=True)
        cleanup = scheduler.DependencyTaskGroup(existing_deps,
                                                self._remove_old_resource,
                                                reverse=True)
        create_new = scheduler.DependencyTaskGroup(new_deps,
                                                   self._create_new_resource)
        update = scheduler.DependencyTaskGroup(new_deps,
                                               self._update_resource)

        if not self.rollback:
            yield cleanup_prev()

        yield create_new()
        try:
            yield update()
        finally:
            prev_deps = self.previous_stack._get_dependencies(
                self.previous_stack.resources.itervalues())
            self.previous_stack.dependencies = prev_deps
        yield cleanup()

    @scheduler.wrappertask
    def _remove_backup_resource(self, prev_res):
        if prev_res.state not in ((prev_res.INIT, prev_res.COMPLETE),
                                  (prev_res.DELETE, prev_res.COMPLETE)):
            logger.debug("Deleting backup resource %s" % prev_res.name)
            yield prev_res.destroy()

    @scheduler.wrappertask
    def _remove_old_resource(self, existing_res):
        res_name = existing_res.name

        if res_name in self.previous_stack:
            yield self._remove_backup_resource(self.previous_stack[res_name])

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
            yield self._create_resource(new_res)

    @staticmethod
    def _exchange_stacks(existing_res, prev_res):
        db_api.resource_exchange_stacks(existing_res.stack.context,
                                        existing_res.id, prev_res.id)
        existing_res.stack, prev_res.stack = prev_res.stack, existing_res.stack
        existing_res.stack[existing_res.name] = existing_res
        prev_res.stack[prev_res.name] = prev_res

    @scheduler.wrappertask
    def _create_resource(self, new_res):
        res_name = new_res.name

        # Clean up previous resource
        if res_name in self.previous_stack:
            prev_res = self.previous_stack[res_name]

            if prev_res.state not in ((prev_res.INIT, prev_res.COMPLETE),
                                      (prev_res.DELETE, prev_res.COMPLETE)):
                # Swap in the backup resource if it is in a valid state,
                # instead of creating a new resource
                if prev_res.status == prev_res.COMPLETE:
                    logger.debug("Swapping in backup Resource %s" % res_name)
                    self._exchange_stacks(self.existing_stack[res_name],
                                          prev_res)
                    return

                logger.debug("Deleting backup Resource %s" % res_name)
                yield prev_res.destroy()

        # Back up existing resource
        if res_name in self.existing_stack:
            logger.debug("Backing up existing Resource %s" % res_name)
            existing_res = self.existing_stack[res_name]
            existing_res.stack = self.previous_stack
            self.previous_stack[res_name] = existing_res
            existing_res.state_set(existing_res.UPDATE, existing_res.COMPLETE)

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
                yield self._create_resource(new_res)
            else:
                logger.info("Resource %s for stack %s updated" %
                            (res_name, self.existing_stack.name))
