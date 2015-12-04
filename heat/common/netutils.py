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

import netaddr


def is_prefix_subset(orig_prefixes, new_prefixes):
    """Check whether orig_prefixes is subset of new_prefixes.


    This takes valid prefix lists for orig_prefixes and new_prefixes,
    returns 'True', if orig_prefixes is subset of new_prefixes.
    """
    orig_set = netaddr.IPSet(orig_prefixes)
    new_set = netaddr.IPSet(new_prefixes)
    return orig_set.issubset(new_set)
