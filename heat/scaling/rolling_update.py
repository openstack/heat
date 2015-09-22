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


def needs_update(targ_capacity, curr_capacity, num_up_to_date):
    """Return whether there are more batch updates to do.

    Inputs are the target size for the group, the current size of the group,
    and the number of members that already have the latest definition.
    """
    return not (num_up_to_date >= curr_capacity == targ_capacity)


def next_batch(targ_capacity, curr_capacity, num_up_to_date, batch_size,
               min_in_service):
    """Return details of the next batch in a batched update.

    The result is a tuple containing the new size of the group and the number
    of members that may receive the new definition (by a combination of
    creating new members and updating existing ones).

    Inputs are the target size for the group, the current size of the group,
    the number of members that already have the latest definition, the batch
    size, and the minimum number of members to keep in service during a rolling
    update.
    """
    assert num_up_to_date <= curr_capacity

    efft_min_sz = min(min_in_service, targ_capacity, curr_capacity)
    efft_bat_sz = min(batch_size, max(targ_capacity - num_up_to_date, 0))

    new_capacity = efft_bat_sz + max(min(curr_capacity,
                                         targ_capacity - efft_bat_sz),
                                     efft_min_sz)

    return new_capacity, efft_bat_sz
