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

from oslo_utils import strutils

from heat.common.i18n import _


def extract_bool(name, value):
    """Convert any true/false string to its corresponding boolean value.

    Value is case insensitive.
    """
    if str(value).lower() not in ('true', 'false'):
        raise ValueError(_('Unrecognized value "%(value)s" for "%(name)s", '
                           'acceptable values are: true, false.')
                         % {'value': value, 'name': name})
    return strutils.bool_from_string(value, strict=True)


def delim_string_to_list(value):
    if value is None:
        return None

    if value == '':
        return []

    return value.split(',')


def extract_int(name, value, allow_zero=True, allow_negative=False):
    if value is None:
        return None

    if not strutils.is_int_like(value):
        raise ValueError(_("Only integer is acceptable by "
                           "'%(name)s'.") % {'name': name})

    if value in ('0', 0):
        if allow_zero:
            return int(value)
        raise ValueError(_("Only non-zero integer is acceptable by "
                           "'%(name)s'.") % {'name': name})
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(_("Value '%(value)s' is invalid for '%(name)s' "
                           "which only accepts integer.") %
                         {'name': name, 'value': value})

    if allow_negative is False and result < 0:
        raise ValueError(_("Value '%(value)s' is invalid for '%(name)s' "
                           "which only accepts non-negative integer.") %
                         {'name': name, 'value': value})

    return result


def extract_tags(subject):
    tags = subject.split(',')
    for tag in tags:
        if len(tag) > 80:
            raise ValueError(_('Invalid tag, "%s" is longer than 80 '
                               'characters') % tag)
    return tags


def extract_template_type(subject):
    template_type = subject.lower()
    if template_type not in ('cfn', 'hot'):
        raise ValueError(_('Invalid template type "%(value)s", valid '
                           'types are: cfn, hot.') %
                         {'value': subject})
    return template_type
