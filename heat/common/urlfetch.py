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

'''
Utility for fetching a resource (e.g. a template) from a URL.
'''

import urllib2
import urlparse

from heat.openstack.common import log as logging
from heat.openstack.common.gettextutils import _

logger = logging.getLogger(__name__)


def get(url):
    '''
    Get the data at the specifier URL.

    The URL must use the http: or https: schemes.
    Raise an IOError if getting the data fails.
    '''
    logger.info(_('Fetching data from %s') % url)

    components = urlparse.urlparse(url)

    if components.scheme not in ('http', 'https'):
        raise urllib2.URLError('Invalid URL scheme %s' % components.scheme)

    response = urllib2.urlopen(url)
    return response.read()
