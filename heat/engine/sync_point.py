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

from heat.objects import sync_point as sync_point_object


def create(context, entity_id, traversal_id, is_update, stack_id):
    """
    Creates an sync point entry in DB.
    """
    values = {'entity_id': entity_id, 'traversal_id': traversal_id,
              'is_update': is_update, 'atomic_key': 0,
              'stack_id': stack_id, 'input_data': {}}
    return sync_point_object.SyncPoint.create(context, values)


def get(context, entity_id, traversal_id, is_update):
    """
    Retrieves a sync point entry from DB.
    """
    return sync_point_object.SyncPoint.get_by_key(context, entity_id,
                                                  traversal_id, is_update)


def delete_all(context, stack_id, traversal_id):
    """
    Deletes all sync points of a stack associated with a particular traversal.
    """
    return sync_point_object.SyncPoint.delete_all_by_stack_and_traversal(
        context, stack_id, traversal_id
    )
