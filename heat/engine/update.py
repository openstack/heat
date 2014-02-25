
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

import copy

from heat.db import api as db_api

from heat.engine import dependencies
from heat.engine import resource
from heat.engine import scheduler

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

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

        self.existing_snippets = dict((n, r.parsed_template())
                                      for n, r in self.existing_stack.items())

    def __repr__(self):
        if self.rollback:
            return '%s Rollback' % str(self.existing_stack)
        else:
            return '%s Update' % str(self.existing_stack)

    @scheduler.wrappertask
    def __call__(self):
        """Return a co-routine that updates the stack."""

        cleanup_prev = scheduler.DependencyTaskGroup(
            self.previous_stack.dependencies,
            self._remove_backup_resource,
            reverse=True)

        update = scheduler.DependencyTaskGroup(self.dependencies(),
                                               self._resource_update)

        if not self.rollback:
            yield cleanup_prev()

        try:
            yield update()
        finally:
            self.previous_stack.reset_dependencies()

    def _resource_update(self, res):
        if res.name in self.new_stack and self.new_stack[res.name] is res:
            return self._process_new_resource_update(res)
        else:
            return self._process_existing_resource_update(res)

    @scheduler.wrappertask
    def _remove_backup_resource(self, prev_res):
        if prev_res.state not in ((prev_res.INIT, prev_res.COMPLETE),
                                  (prev_res.DELETE, prev_res.COMPLETE)):
            logger.debug(_("Deleting backup resource %s") % prev_res.name)
            yield prev_res.destroy()

    @staticmethod
    def _exchange_stacks(existing_res, prev_res):
        db_api.resource_exchange_stacks(existing_res.stack.context,
                                        existing_res.id, prev_res.id)
        prev_stack, existing_stack = prev_res.stack, existing_res.stack
        prev_stack[existing_res.name] = existing_res
        existing_stack[prev_res.name] = prev_res

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
                    logger.debug(_("Swapping in backup Resource %s") %
                                 res_name)
                    self._exchange_stacks(self.existing_stack[res_name],
                                          prev_res)
                    return

                logger.debug(_("Deleting backup Resource %s") % res_name)
                yield prev_res.destroy()

        # Back up existing resource
        if res_name in self.existing_stack:
            logger.debug(_("Backing up existing Resource %s") % res_name)
            existing_res = self.existing_stack[res_name]
            self.previous_stack[res_name] = existing_res
            existing_res.state_set(existing_res.UPDATE, existing_res.COMPLETE)

        self.existing_stack[res_name] = new_res
        yield new_res.create()

    @scheduler.wrappertask
    def _process_new_resource_update(self, new_res):
        res_name = new_res.name

        if res_name in self.existing_stack:
            existing_res = self.existing_stack[res_name]
            try:
                yield self._update_in_place(existing_res,
                                            new_res)
            except resource.UpdateReplace:
                pass
            else:
                logger.info(_("Resource %(res_name)s for stack %(stack_name)s"
                            " updated") % {
                                'res_name': res_name,
                                'stack_name': self.existing_stack.name})
                return

        yield self._create_resource(new_res)

    def _update_in_place(self, existing_res, new_res):
        existing_snippet = self.existing_snippets[existing_res.name]
        prev_res = self.previous_stack.get(new_res.name)

        # Note the new resource snippet is resolved in the context
        # of the existing stack (which is the stack being updated)
        raw_snippet = copy.deepcopy(new_res.t)
        parsed_snippet = self.existing_stack.resolve_static_data(raw_snippet)
        new_snippet = self.existing_stack.resolve_runtime_data(parsed_snippet)

        return existing_res.update(new_snippet, existing_snippet,
                                   prev_resource=prev_res)

    @scheduler.wrappertask
    def _process_existing_resource_update(self, existing_res):
        res_name = existing_res.name

        if res_name in self.previous_stack:
            yield self._remove_backup_resource(self.previous_stack[res_name])

        if res_name in self.new_stack:
            new_res = self.new_stack[res_name]
            if new_res.state == (new_res.INIT, new_res.COMPLETE):
                # Already updated in-place
                return

        if existing_res.stack is not self.previous_stack:
            yield existing_res.destroy()

        if res_name not in self.new_stack:
            del self.existing_stack[res_name]

    def dependencies(self):
        '''
        Return a Dependencies object representing the dependencies between
        update operations to move from an existing stack definition to a new
        one.
        '''
        existing_deps = self.existing_stack.dependencies
        new_deps = self.new_stack.dependencies

        def edges():
            # Create/update the new stack's resources in create order
            for e in new_deps.graph().edges():
                yield e
            # Destroy/cleanup the old stack's resources in delete order
            for e in existing_deps.graph(reverse=True).edges():
                yield e
            # Don't cleanup old resources until after they have been replaced
            for name, res in self.existing_stack.iteritems():
                if name in self.new_stack:
                    yield (res, self.new_stack[name])

        return dependencies.Dependencies(edges())
