#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""A test module to exercise the Heat API with gabbi.  """

import os

from gabbi import driver
from six.moves.urllib import parse as urlparse

from heat_integrationtests.common import clients
from heat_integrationtests.common import config
from heat_integrationtests.common import test

TESTS_DIR = 'gabbits'


def load_tests(loader, tests, pattern):
    """Provide a TestSuite to the discovery process."""
    test_dir = os.path.join(os.path.dirname(__file__), TESTS_DIR)

    conf = config.CONF.heat_plugin
    if conf.auth_url is None:
        # It's not configured, let's not load tests
        return
    manager = clients.ClientManager(conf)
    endpoint = manager.identity_client.get_endpoint_url(
        'orchestration', conf.region)
    host = urlparse.urlparse(endpoint).hostname
    os.environ['OS_TOKEN'] = manager.identity_client.auth_token
    os.environ['PREFIX'] = test.rand_name('api')

    return driver.build_tests(test_dir, loader, host=host,
                              url=endpoint, test_loader_name=__name__)
