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

import math

ADJUSTMENT_TYPES = (
    EXACT_CAPACITY, CHANGE_IN_CAPACITY, PERCENT_CHANGE_IN_CAPACITY) = (
    'exact_capacity', 'change_in_capacity', 'percent_change_in_capacity')

CFN_ADJUSTMENT_TYPES = (
    CFN_EXACT_CAPACITY, CFN_CHANGE_IN_CAPACITY,
    CFN_PERCENT_CHANGE_IN_CAPACITY) = ('ExactCapacity', 'ChangeInCapacity',
                                       'PercentChangeInCapacity')


def calculate_new_capacity(current, adjustment, adjustment_type,
                           min_adjustment_step, minimum, maximum):
    """Calculates new capacity from the given adjustments.

    Given the current capacity, calculates the new capacity which results
    from applying the given adjustment of the given adjustment-type.  The
    new capacity will be kept within the maximum and minimum bounds.
    """
    def _get_minimum_adjustment(adjustment, min_adjustment_step):
        if min_adjustment_step and min_adjustment_step > abs(adjustment):
            adjustment = (min_adjustment_step if adjustment > 0
                          else -min_adjustment_step)
        return adjustment

    if adjustment_type in (CHANGE_IN_CAPACITY, CFN_CHANGE_IN_CAPACITY):
        new_capacity = current + adjustment
    elif adjustment_type in (EXACT_CAPACITY, CFN_EXACT_CAPACITY):
        new_capacity = adjustment
    else:
        # PercentChangeInCapacity
        delta = current * adjustment / 100.0
        if math.fabs(delta) < 1.0:
            rounded = int(math.ceil(delta) if delta > 0.0
                          else math.floor(delta))
        else:
            rounded = int(math.floor(delta) if delta > 0.0
                          else math.ceil(delta))
        adjustment = _get_minimum_adjustment(rounded, min_adjustment_step)
        new_capacity = current + adjustment

    if new_capacity > maximum:
        return maximum

    if new_capacity < minimum:
        return minimum

    return new_capacity
