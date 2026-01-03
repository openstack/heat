#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ast
import tenacity

from oslo_log import log as logging

from heat.common import exception
from heat.objects import sync_point as sync_point_object

LOG = logging.getLogger(__name__)


KEY_SEPERATOR = ':'


def _dump_list(items, separator=', '):
    return separator.join(map(str, items))


def make_key(*components):
    assert len(components) >= 2
    return _dump_list(components, KEY_SEPERATOR)


def create(context, entity_id, traversal_id, is_update, stack_id):
    """Creates a sync point entry in DB."""
    values = {'entity_id': entity_id, 'traversal_id': traversal_id,
              'is_update': is_update, 'atomic_key': 0,
              'stack_id': stack_id, 'input_data': {}}
    return sync_point_object.SyncPoint.create(context, values)


def get(context, entity_id, traversal_id, is_update):
    """Retrieves a sync point entry from DB."""
    sync_point = sync_point_object.SyncPoint.get_by_key(context, entity_id,
                                                        traversal_id,
                                                        is_update)
    if sync_point is None:
        key = (entity_id, traversal_id, is_update)
        raise exception.EntityNotFound(entity='Sync Point', name=key)

    return sync_point


def delete_all(context, stack_id, traversal_id):
    """Deletes all sync points of a stack associated with a traversal_id."""
    return sync_point_object.SyncPoint.delete_all_by_stack_and_traversal(
        context, stack_id, traversal_id
    )


def update_input_data(context, entity_id, current_traversal,
                      is_update, atomic_key, input_data=None, extra_data=None):
    rows_updated = sync_point_object.SyncPoint.update_input_data(
        context, entity_id, current_traversal, is_update, atomic_key,
        input_data, extra_data)

    return rows_updated


def str_pack_tuple(t):
    return 'tuple:' + str(tuple(t))


def _str_unpack_tuple(s):
    s = s[s.index(':') + 1:]
    return ast.literal_eval(s)


def _deserialize(d):
    d2 = {}
    for k, v in d.items():
        if isinstance(k, str) and k.startswith('tuple:('):
            k = _str_unpack_tuple(k)
        if isinstance(v, dict):
            v = _deserialize(v)
        d2[k] = v
    return d2


def _serialize(d):
    d2 = {}
    for k, v in d.items():
        if isinstance(k, tuple):
            k = str_pack_tuple(k)
        if isinstance(v, dict):
            v = _serialize(v)
        d2[k] = v
    return d2


def deserialize_input_data(db_input_data):
    return _deserialize_data(db_input_data, 'input_data')


def deserialize_extra_data(db_extra_data):
    return _deserialize_data(db_extra_data, 'extra_data')


def _deserialize_data(db_data, key):
    db_data = db_data.get(key)
    if not db_data:
        return {}
    return dict(_deserialize(db_data))


def serialize_input_data(input_data):
    return _serialize_data(input_data, 'input_data')


def serialize_extra_data(extra_data):
    return _serialize_data(extra_data, 'extra_data')


def _serialize_data(data, key):
    return {key: _serialize(data)}


def update_sync_point(cnxt, entity_id, current_traversal, is_update,
                      predecessors, new_data, new_resource_failures=None,
                      is_skip=False):
    """Update a sync point atomically with new data and failures.

    Retry waits up to 60 seconds at most, with exponentially increasing
    amounts of jitter per resource still outstanding.
    """
    wait_strategy = tenacity.wait_random_exponential(max=60)

    def init_jitter(existing_input_data):
        nconflicts = max(0, len(predecessors) - len(existing_input_data) - 1)
        # 10ms per potential conflict, up to a max of 10s in total
        return min(nconflicts, 1000) * 0.01

    @tenacity.retry(
        retry=tenacity.retry_if_result(lambda r: r is None),
        wait=wait_strategy
    )
    def _sync():
        sync_point = get(cnxt, entity_id, current_traversal, is_update)
        input_data = deserialize_input_data(sync_point.input_data)
        extra_data = deserialize_extra_data(
            sync_point.extra_data) if sync_point.extra_data is not None else {}
        resource_failures = extra_data.get("resource_failures", {})
        skip_propagate = extra_data.get("skip_propagate", False)
        if new_resource_failures is not None:
            resource_failures.update(new_resource_failures)
            extra_data.update({"resource_failures": resource_failures})
        if is_skip:
            extra_data.update({"skip_propagate": is_skip})
            skip_propagate = is_skip
        if not extra_data:
            extra_data = None
        else:
            extra_data = serialize_extra_data(extra_data)
        wait_strategy.multiplier = init_jitter(input_data)
        if new_data is not None:
            input_data.update(new_data)
        rows_updated = update_input_data(
            cnxt, entity_id, current_traversal, is_update,
            sync_point.atomic_key,
            serialize_input_data(input_data), extra_data)
        return (input_data, resource_failures,
                skip_propagate) if rows_updated else None
    return _sync()


def sync(cnxt, entity_id, current_traversal, is_update, propagate,
         predecessors, new_data, new_resource_failures=None,
         is_skip=False):
    """Synchronize resource state and propagate when all predecessors done.

    This function updates the sync point with new data and resource failures,
    and calls the propagate callback when all predecessors have reported.
    """
    result = update_sync_point(
        cnxt, entity_id, current_traversal, is_update,
        predecessors, new_data, new_resource_failures,
        is_skip=is_skip)
    if result is None:
        # Sync point update failed (possibly deleted by another traversal)
        LOG.warning('[%s] Sync point update failed for entity %s',
                    current_traversal, entity_id)
        return
    input_data, resource_failures, skip_propagate = result
    waiting = predecessors - set(input_data)
    key = make_key(entity_id, current_traversal, is_update)
    if waiting:
        LOG.debug('[%s] Waiting %s: Got %s; still need %s',
                  key, entity_id, _dump_list(input_data), _dump_list(waiting))
    else:
        LOG.debug('[%s] Ready %s: Got %s',
                  key, entity_id, _dump_list(input_data))
        propagate(entity_id, serialize_input_data(input_data),
                  resource_failures, skip_propagate)
