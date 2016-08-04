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

import six

from heat.common import environment_format as env_fmt

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


def merge_list(old, new):
    """merges lists and comma delimited lists."""
    if not old:
        return new

    if isinstance(new, list):
        old.extend(new)
        return old
    else:
        return ','.join([old, new])


def merge_map(old, new, deep_merge=False):
    """Merge nested dictionaries."""
    if not old:
        return new

    for k, v in new.items():
        if v:
            if not deep_merge:
                old[k] = v
            elif isinstance(v, collections.Mapping):
                old_v = old.get(k)
                old[k] = merge_map(old_v, v, deep_merge) if old_v else v
            elif (isinstance(v, collections.Sequence) and
                    not isinstance(v, six.string_types)):
                old_v = old.get(k)
                old[k] = merge_list(old_v, v) if old_v else v
            else:
                old[k] = v

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
    if not environment_files:
        return

    for filename in environment_files:
        raw_env = files[filename]
        parsed_env = env_fmt.parse(raw_env)
        for section_key, section_value in parsed_env.items():
            if section_value:
                params[section_key] = merge_map(params[section_key],
                                                section_value,
                                                deep_merge=True)
