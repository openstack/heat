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

from oslo_log import log as logging
import six


LOG = logging.getLogger(__name__)


def log_fail_msg(manager, entrypoint, exception):
    LOG.warning('Encountered exception while loading %(module_name)s: '
                '"%(message)s". Not using %(name)s.',
                {'module_name': entrypoint.module_name,
                 'message': getattr(exception, 'message',
                                    six.text_type(exception)),
                 'name': entrypoint.name})
