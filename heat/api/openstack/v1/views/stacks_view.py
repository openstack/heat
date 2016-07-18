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

import itertools

from heat.api.openstack.v1 import util
from heat.api.openstack.v1.views import views_common
from heat.rpc import api as rpc_api

_collection_name = 'stacks'

basic_keys = (
    rpc_api.STACK_ID,
    rpc_api.STACK_NAME,
    rpc_api.STACK_DESCRIPTION,
    rpc_api.STACK_STATUS,
    rpc_api.STACK_STATUS_DATA,
    rpc_api.STACK_CREATION_TIME,
    rpc_api.STACK_DELETION_TIME,
    rpc_api.STACK_UPDATED_TIME,
    rpc_api.STACK_OWNER,
    rpc_api.STACK_PARENT,
    rpc_api.STACK_USER_PROJECT_ID,
    rpc_api.STACK_TAGS,
)


def format_stack(req, stack, keys=None, include_project=False):
    def transform(key, value):
        if keys and key not in keys:
            return

        if key == rpc_api.STACK_ID:
            yield ('id', value['stack_id'])
            yield ('links', [util.make_link(req, value)])
            if include_project:
                yield ('project', value['tenant'])
        elif key == rpc_api.STACK_ACTION:
            return
        elif (key == rpc_api.STACK_STATUS and
              rpc_api.STACK_ACTION in stack):
            # To avoid breaking API compatibility, we join RES_ACTION
            # and RES_STATUS, so the API format doesn't expose the
            # internal split of state into action/status
            yield (key, '_'.join((stack[rpc_api.STACK_ACTION], value)))
        else:
            # TODO(zaneb): ensure parameters can be formatted for XML
            # elif key == rpc_api.STACK_PARAMETERS:
            #     return key, json.dumps(value)
            yield (key, value)

    return dict(itertools.chain.from_iterable(
        transform(k, v) for k, v in stack.items()))


def collection(req, stacks, count=None, include_project=False):
    keys = basic_keys
    formatted_stacks = [format_stack(req, s, keys, include_project)
                        for s in stacks]

    result = {'stacks': formatted_stacks}
    links = views_common.get_collection_links(req, formatted_stacks)
    if links:
        result['links'] = links
    if count is not None:
        result['count'] = count

    return result
