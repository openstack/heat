#!/usr/bin/env python
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

from __future__ import print_function

import sys

from oslo.config import cfg
from oslo import i18n

from heat.db import migration
from heat.openstack.common import log as logging

# fixme(elynn): Since install() is deprecated, we should remove it in
# the future
i18n.install('heat')

LOG = logging.getLogger(__name__)


if __name__ == '__main__':
    print('*******************************************', file=sys.stderr)
    print('Deprecated: use heat-manage db_sync instead', file=sys.stderr)
    print('*******************************************', file=sys.stderr)
    cfg.CONF(project='heat', prog='heat-engine')

    try:
        migration.db_sync()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
