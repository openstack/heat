#    Copyright 2015 Intel Corp.
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

"""Heat common internal object model"""

import weakref

from oslo_versionedobjects import base as ovoo_base


class HeatObjectRegistry(ovoo_base.VersionedObjectRegistry):
    pass


class HeatObject(ovoo_base.VersionedObject):
    OBJ_PROJECT_NAMESPACE = 'heat'
    VERSION = '1.0'

    @property
    def _context(self):
        if self._contextref is None:
            return
        ctxt = self._contextref()
        assert ctxt is not None, "Need a reference to the context"
        return ctxt

    @_context.setter
    def _context(self, context):
        if context:
            self._contextref = weakref.ref(context)
        else:
            self._contextref = None
