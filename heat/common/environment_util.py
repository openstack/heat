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
import collections

from heat.common import environment_format

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


def deep_update(old, new):
    '''Merge nested dictionaries.'''
    for k, v in new.items():
        if isinstance(v, collections.Mapping):
            r = deep_update(old.get(k, {}), v)
            old[k] = r
        else:
            old[k] = new[k]
    return old


def merge_environments(environment_files, files, params):
    """Merges environment files into the stack input parameters.

    If a list of environment files have been specified, this call will
    pull the contents of each from the files dict, parse them as
    environments, and merge them into the stack input params. This
    behavior is the same as earlier versions of the Heat client that
    performed this params population client-side.

    :param environment_files: ordered names of the environment files
           found in the files dict
    :type  environment_files: list or None
    :param files: mapping of stack filenames to contents
    :type  files: dict
    :param params: parameters describing the stack
    :type  dict:
    """
    if environment_files:
        for filename in environment_files:
            raw_env = files[filename]
            parsed_env = environment_format.parse(raw_env)
            deep_update(params, parsed_env)
