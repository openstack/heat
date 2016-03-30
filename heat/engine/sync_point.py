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
from oslo_log import log as logging
import six

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
                      is_update, atomic_key, input_data):
    rows_updated = sync_point_object.SyncPoint.update_input_data(
        context, entity_id, current_traversal, is_update, atomic_key,
        input_data)

    return rows_updated


def _str_pack_tuple(t):
    return u'tuple:' + str(t)


def _str_unpack_tuple(s):
    s = s[s.index(':') + 1:]
    return ast.literal_eval(s)


def _deserialize(d):
    d2 = {}
    for k, v in d.items():
        if isinstance(k, six.string_types) and k.startswith(u'tuple:('):
            k = _str_unpack_tuple(k)
        if isinstance(v, dict):
            v = _deserialize(v)
        d2[k] = v
    return d2


def _serialize(d):
    d2 = {}
    for k, v in d.items():
        if isinstance(k, tuple):
            k = _str_pack_tuple(k)
        if isinstance(v, dict):
            v = _serialize(v)
        d2[k] = v
    return d2


def deserialize_input_data(db_input_data):
    db_input_data = db_input_data.get('input_data')
    if not db_input_data:
        return {}

    return dict(_deserialize(db_input_data))


def serialize_input_data(input_data):
    return {'input_data': _serialize(input_data)}


def sync(cnxt, entity_id, current_traversal, is_update, propagate,
         predecessors, new_data):
    rows_updated = None
    sync_point = None
    input_data = None
    while not rows_updated:
        # TODO(sirushtim): Add a conf option to add no. of retries
        sync_point = get(cnxt, entity_id, current_traversal, is_update)
        input_data = deserialize_input_data(sync_point.input_data)
        input_data.update(new_data)
        rows_updated = update_input_data(
            cnxt, entity_id, current_traversal, is_update,
            sync_point.atomic_key, serialize_input_data(input_data))

    waiting = predecessors - set(input_data)
    key = make_key(entity_id, current_traversal, is_update)
    if waiting:
        LOG.debug('[%s] Waiting %s: Got %s; still need %s',
                  key, entity_id, _dump_list(input_data), _dump_list(waiting))
    else:
        LOG.debug('[%s] Ready %s: Got %s',
                  key, entity_id, _dump_list(input_data))
        propagate(entity_id, serialize_input_data(input_data))
