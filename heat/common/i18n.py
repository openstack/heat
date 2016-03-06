# Copyright 2014 IBM Corp.
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

# It's based on oslo.i18n usage in OpenStack Keystone project and
# recommendations from http://docs.openstack.org/developer/oslo.i18n/usage.html

import six

import oslo_i18n as i18n
from oslo_utils import encodeutils


_translators = i18n.TranslatorFactory(domain='heat')

# The primary translation function using the well-known name "_"
_ = _translators.primary

# Translators for log levels.
#
# The abbreviated names are meant to reflect the usual use of a short
# name like '_'. The "L" is for "log" and the other letter comes from
# the level.
_LI = _translators.log_info
_LW = _translators.log_warning
_LE = _translators.log_error
_LC = _translators.log_critical


def repr_wraper(klass):
    """A decorator that defines __repr__ method under Python 2.

    Under Python 2 it will encode repr return value to str type.
    Under Python 3 it does nothing.
    """
    if six.PY2:
        if '__repr__' not in klass.__dict__:
            raise ValueError("@repr_wraper cannot be applied "
                             "to %s because it doesn't define __repr__()." %
                             klass.__name__)
        klass._repr = klass.__repr__
        klass.__repr__ = lambda self: encodeutils.safe_encode(self._repr())
    return klass
