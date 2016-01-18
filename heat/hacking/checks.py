# Copyright (c) 2016 OpenStack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import re


"""
Guidelines for writing new hacking checks

- Use only for Heat specific tests. OpenStack general tests
  should be submitted to the common 'hacking' module.
- Pick numbers in the range H3xx. Find the current test with
  the highest allocated number and then pick the next value.
- Keep the test method code in the source file ordered based
  on the Heat3xx value.
- List the new rule in the top level HACKING.rst file
- Add test cases for each new rule to heat/tests/test_hacking.py

"""


def no_log_warn(logical_line):
    """Disallow 'LOG.warn('

    https://bugs.launchpad.net/tempest/+bug/1508442

    Heat301
    """
    if logical_line.startswith('LOG.warn('):
        yield(0, 'Heat301 Use LOG.warning() rather than LOG.warn()')


def check_python3_no_iteritems(logical_line):
    msg = ("Heat302: Use dict.items() instead of dict.iteritems().")

    if re.search(r".*\.iteritems\(\)", logical_line):
        yield(0, msg)


def check_python3_no_iterkeys(logical_line):
    msg = ("Heat303: Use dict.keys() instead of dict.iterkeys().")

    if re.search(r".*\.iterkeys\(\)", logical_line):
        yield(0, msg)


def check_python3_no_itervalues(logical_line):
    msg = ("Heat304: Use dict.values() instead of dict.itervalues().")

    if re.search(r".*\.itervalues\(\)", logical_line):
        yield(0, msg)


def factory(register):
    register(no_log_warn)
    register(check_python3_no_iteritems)
    register(check_python3_no_iterkeys)
    register(check_python3_no_itervalues)
