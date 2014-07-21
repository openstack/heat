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

"""
Utilities for handling ISO 8601 duration format.
"""

import random
import re


iso_duration_re = re.compile('PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$')


def parse_isoduration(duration):
    """
    Convert duration in ISO 8601 format to second(s).

    Year, Month, Week, and Day designators are not supported.
    Example: 'PT12H30M5S'
    """
    result = iso_duration_re.match(duration)
    if not result:
        raise ValueError(_('Only ISO 8601 duration format of the form '
                           'PT#H#M#S is supported.'))

    t = 0
    t += (3600 * int(result.group(1))) if result.group(1) else 0
    t += (60 * int(result.group(2))) if result.group(2) else 0
    t += int(result.group(3)) if result.group(3) else 0

    return t


def retry_backoff_delay(attempt, scale_factor=1.0, jitter_max=0.0):
    """
    Calculate an exponential backoff delay with jitter.

    Delay is calculated as
    2^attempt + (uniform random from [0,1) * jitter_max)

    :param attempt: The count of the current retry attempt
    :param scale_factor: Multiplier to scale the exponential delay by
    :param jitter_max: Maximum of random seconds to add to the delay
    :returns: Seconds since epoch to wait until
    """
    exp = float(2 ** attempt) * float(scale_factor)
    if jitter_max == 0.0:
        return exp
    return exp + random.random() * jitter_max
