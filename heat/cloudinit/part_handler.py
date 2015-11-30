# part-handler
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

import datetime
import errno
import os
import sys


def list_types():
    return(["text/x-cfninitdata"])


def handle_part(data, ctype, filename, payload):
    if ctype == "__begin__":
        try:
            os.makedirs('/var/lib/heat-cfntools', int("700", 8))
        except OSError:
            ex_type, e, tb = sys.exc_info()
            if e.errno != errno.EEXIST:
                raise
        return

    if ctype == "__end__":
        return

    timestamp = datetime.datetime.now()
    with open('/var/log/part-handler.log', 'a') as log:
        log.write('%s filename:%s, ctype:%s\n' % (timestamp, filename, ctype))

    if ctype == 'text/x-cfninitdata':
        with open('/var/lib/heat-cfntools/%s' % filename, 'w') as f:
            f.write(payload)

        # TODO(sdake) hopefully temporary until users move to heat-cfntools-1.3
        with open('/var/lib/cloud/data/%s' % filename, 'w') as f:
            f.write(payload)
