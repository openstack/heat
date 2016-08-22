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

ALLOWED_PARAM_MERGE_STRATEGIES = (OVERWRITE, MERGE, DEEP_MERGE) = (
    'overwrite', 'merge', 'deep_merge')


def get_param_merge_strategy(merge_strategies, param_key):

    if merge_strategies is None:
        return OVERWRITE

    env_default = merge_strategies.get('default', OVERWRITE)

    merge_strategy = merge_strategies.get(param_key, env_default)
    if merge_strategy in ALLOWED_PARAM_MERGE_STRATEGIES:
        return merge_strategy

    return env_default
