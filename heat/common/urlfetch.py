
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

from oslo.config import cfg
import requests
from requests import exceptions

from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging
from heat.openstack.common.py3kcompat import urlutils

cfg.CONF.import_opt('max_template_size', 'heat.common.config')

logger = logging.getLogger(__name__)


def get(url, allowed_schemes=('http', 'https')):
    '''
    Get the data at the specifier URL.

    The URL must use the http: or https: schemes.
    The file: scheme is also supported if you override
    the allowed_schemes argument.
    Raise an IOError if getting the data fails.
    '''
    logger.info(_('Fetching data from %s') % url)

    components = urlutils.urlparse(url)

    if components.scheme not in allowed_schemes:
        raise IOError(_('Invalid URL scheme %s') % components.scheme)

    if components.scheme == 'file':
        try:
            return urlutils.urlopen(url).read()
        except urlutils.URLError as uex:
            raise IOError(_('Failed to retrieve template: %s') % str(uex))

    try:
        resp = requests.get(url, stream=True)
        resp.raise_for_status()

        # We cannot use resp.text here because it would download the
        # entire file, and a large enough file would bring down the
        # engine.  The 'Content-Length' header could be faked, so it's
        # necessary to download the content in chunks to until
        # max_template_size is reached.  The chunk_size we use needs
        # to balance CPU-intensive string concatenation with accuracy
        # (eg. it's possible to fetch 1000 bytes greater than
        # max_template_size with a chunk_size of 1000).
        reader = resp.iter_content(chunk_size=1000)
        result = ""
        for chunk in reader:
            result += chunk
            if len(result) > cfg.CONF.max_template_size:
                raise IOError("Template exceeds maximum allowed size (%s "
                              "bytes)" % cfg.CONF.max_template_size)
        return result

    except exceptions.RequestException as ex:
        raise IOError(_('Failed to retrieve template: %s') % str(ex))
