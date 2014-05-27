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

from heat.common import exception
from heat.engine import constraints
from heat.engine.resources import glance_utils


class ImageConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (exception.ImageNotFound,)

    def validate_with_client(self, client, value):
        glance_client = client.glance()
        glance_utils.get_image_id(glance_client, value)


def constraint_mapping():
    return {'glance.image': ImageConstraint}
