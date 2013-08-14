# vim: tabstop=4 shiftwidth=4 softtabstop=4
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
#
# The MIT License
#
# ext/mutable.py
# Copyright (C) 2005-2013 the SQLAlchemy authors
# and contributors <see AUTHORS file>
#
# This module is part of SQLAlchemy and is released under
# the MIT License: http://www.opensource.org/lic enses/mit-license.php
"""
Submitted on behalf of a third-party: sqlalchemy
"""
from sqlalchemy.ext.mutable import Mutable


class MutableDict(Mutable, dict):
    """A dictionary type that implements :class:`.Mutable`.

    .. versionadded:: 0.8

    """

    def __setitem__(self, key, value):
        """Detect dictionary set events and emit change events."""
        dict.__setitem__(self, key, value)
        self.changed()

    def __delitem__(self, key):
        """Detect dictionary del events and emit change events."""
        dict.__delitem__(self, key)
        self.changed()

    def clear(self):
        dict.clear(self)
        self.changed()

    @classmethod
    def coerce(cls, key, value):
        """Convert plain dictionary to MutableDict."""
        if not isinstance(value, MutableDict):
            if isinstance(value, dict):
                return MutableDict(value)
            return Mutable.coerce(key, value)
        else:
            return value

    def __getstate__(self):
        return dict(self)

    def __setstate__(self, state):
        self.update(state)
