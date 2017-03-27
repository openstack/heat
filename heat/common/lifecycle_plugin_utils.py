
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

"""Utility for fetching and running plug point implementation classes."""

from oslo_log import log as logging

from heat.engine import resources

LOG = logging.getLogger(__name__)
pp_class_instances = None


def get_plug_point_class_instances():
    """Instances of classes that implements pre/post stack operation methods.

    Get list of instances of classes that (may) implement pre and post
    stack operation methods.

    The list of class instances is sorted using get_ordinal methods
    on the plug point classes. If class1.ordinal() < class2.ordinal(),
    then class1 will be before before class2 in the list.
    """
    global pp_class_instances
    if pp_class_instances is None:
        pp_class_instances = []
        pp_classes = []
        try:
            slps = resources.global_env().get_stack_lifecycle_plugins()
            pp_classes = [cls for name, cls in slps]
        except Exception:
            LOG.exception("failed to get lifecycle plug point classes")

        for ppc in pp_classes:
            try:
                pp_class_instances.append(ppc())
            except Exception:
                LOG.exception(
                    "failed to instantiate stack lifecycle class %s", ppc)
        try:
            pp_class_instances = sorted(pp_class_instances,
                                        key=lambda ppci: ppci.get_ordinal())
        except Exception:
            LOG.exception("failed to sort lifecycle plug point classes")
    return pp_class_instances


def do_pre_ops(cnxt, stack, current_stack=None, action=None):
    """Call available pre-op methods sequentially.

    In order determined with get_ordinal(), with parameters context, stack,
    current_stack, action.

    On failure of any pre_op method, will call post-op methods corresponding
    to successful calls of pre-op methods.
    """
    cinstances = get_plug_point_class_instances()
    if action is None:
        action = stack.action
    failure, failure_exception_message, success_count = _do_ops(
        cinstances, 'do_pre_op', cnxt, stack, current_stack, action, None)

    if failure:
        cinstances = cinstances[0:success_count]
        _do_ops(cinstances, 'do_post_op', cnxt, stack, current_stack,
                action, True)
        raise Exception(failure_exception_message)


def do_post_ops(cnxt, stack, current_stack=None, action=None,
                is_stack_failure=False):
    """Call available post-op methods sequentially.

    In order determined with get_ordinal(), with parameters context, stack,
    current_stack, action, is_stack_failure.
    """
    cinstances = get_plug_point_class_instances()
    if action is None:
        action = stack.action
    _do_ops(cinstances, 'do_post_op', cnxt, stack, current_stack, action, None)


def _do_ops(cinstances, opname, cnxt, stack, current_stack=None, action=None,
            is_stack_failure=None):
    success_count = 0
    failure = False
    failure_exception_message = None
    for ci in cinstances:
        op = getattr(ci, opname, None)
        if callable(op):
            try:
                if is_stack_failure is not None:
                    op(cnxt, stack, current_stack, action, is_stack_failure)
                else:
                    op(cnxt, stack, current_stack, action)
                success_count += 1
            except Exception as ex:
                LOG.exception(
                    "%(opname)s %(ci)s failed for %(a)s on %(sid)s",
                    {'opname': opname, 'ci': type(ci),
                     'a': action, 'sid': stack.id})
                failure = True
                failure_exception_message = ex.args[0] if ex.args else str(ex)
                break
        LOG.info("done with class=%(c)s, stackid=%(sid)s, action=%(a)s",
                 {'c': type(ci), 'sid': stack.id, 'a': action})
    return (failure, failure_exception_message, success_count)
