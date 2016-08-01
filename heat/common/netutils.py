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
import re

from heat.common.i18n import _

DNS_LABEL_MAX_LEN = 63
DNS_LABEL_REGEX = "[a-z0-9-]{1,%d}$" % DNS_LABEL_MAX_LEN
FQDN_MAX_LEN = 255


def is_prefix_subset(orig_prefixes, new_prefixes):
    """Check whether orig_prefixes is subset of new_prefixes.


    This takes valid prefix lists for orig_prefixes and new_prefixes,
    returns 'True', if orig_prefixes is subset of new_prefixes.
    """
    orig_set = netaddr.IPSet(orig_prefixes)
    new_set = netaddr.IPSet(new_prefixes)
    return orig_set.issubset(new_set)


def validate_dns_format(data):
    if not data:
        return
    trimmed = data if not data.endswith('.') else data[:-1]
    if len(trimmed) > FQDN_MAX_LEN:
        raise ValueError(
            _("'%(data)s' exceeds the %(max_len)s character FQDN limit") % {
                'data': trimmed,
                'max_len': FQDN_MAX_LEN})
    names = trimmed.split('.')
    for name in names:
        if not name:
            raise ValueError(_("Encountered an empty component."))
        if name.endswith('-') or name.startswith('-'):
            raise ValueError(
                _("Name '%s' must not start or end with a hyphen.") % name)
        if not re.match(DNS_LABEL_REGEX, name):
            raise ValueError(
                _("Name '%(name)s' must be 1-%(max_len)s characters long, "
                  "each of which can only be alphanumeric or "
                  "a hyphen.") % {'name': name,
                                  'max_len': DNS_LABEL_MAX_LEN})
    # RFC 1123 hints that a Top Level Domain(TLD) can't be all numeric.
    # Last part is a TLD, if it's a FQDN.
    if (data.endswith('.') and len(names) > 1
            and re.match("^[0-9]+$", names[-1])):
        raise ValueError(_("TLD '%s' must not be all numeric.") % names[-1])
