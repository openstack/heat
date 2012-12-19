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

import functools
from heat.common import exception
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)

SUCCESS = 0
FAILURE = 1


def catch_error(action):
    """Decorator to provide sensible default error handling for CLI actions."""
    def wrap(func):
        @functools.wraps(func)
        def wrapper(*arguments, **kwargs):
            try:
                ret = func(*arguments, **kwargs)
                return SUCCESS if ret is None else ret
            except exception.NotAuthorized:
                LOG.error("Not authorized to make this request. Check " +
                          "your credentials (OS_USERNAME, OS_PASSWORD, " +
                          "OS_TENANT_NAME, OS_AUTH_URL and OS_AUTH_STRATEGY).")
                return FAILURE
            except exception.ClientConfigurationError:
                raise
            except exception.KeystoneError, e:
                LOG.error("Keystone did not finish the authentication and "
                          "returned the following message:\n\n%s" % e.message)
                return FAILURE
            except Exception, e:
                options = arguments[0]
                if options.debug:
                    raise
                LOG.error("Failed to %s. Got error:" % action)
                pieces = unicode(e).split('\n')
                for piece in pieces:
                    LOG.error(piece)
                return FAILURE

        return wrapper
    return wrap
