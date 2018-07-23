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

from oslo_serialization import jsonutils
import six

from heat.common import environment_format as env_fmt
from heat.common import exception
from heat.common.i18n import _

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
        if v is not None:
            if not deep_merge:
                old[k] = v
            elif isinstance(v, collections.Mapping):
                old_v = old.get(k)
                old[k] = merge_map(old_v, v, deep_merge) if old_v else v
            elif (isinstance(v, collections.Sequence) and
                    not isinstance(v, six.string_types)):
                old_v = old.get(k)
                old[k] = merge_list(old_v, v) if old_v else v
            elif isinstance(v, six.string_types):
                old[k] = ''.join([old.get(k, ''), v])
            else:
                old[k] = v

    return old


def parse_param(p_val, p_schema):
    try:
        if p_schema.type == p_schema.MAP:
            if not isinstance(p_val, six.string_types):
                p_val = jsonutils.dumps(p_val)
            if p_val:
                return jsonutils.loads(p_val)
        elif not isinstance(p_val, collections.Sequence):
            raise ValueError()
    except (ValueError, TypeError) as err:
        msg = _("Invalid parameter in environment %s.") % six.text_type(err)
        raise ValueError(msg)
    return p_val


def merge_parameters(old, new, param_schemata, strategies_in_file,
                     available_strategies, env_file):

    def param_merge(p_key, p_value, p_schema, deep_merge=False):
        p_type = p_schema.type
        p_value = parse_param(p_value, p_schema)
        if p_type == p_schema.MAP:
            old[p_key] = merge_map(old.get(p_key, {}), p_value, deep_merge)
        elif p_type == p_schema.LIST:
            old[p_key] = merge_list(old.get(p_key), p_value)
        elif p_type == p_schema.STRING:
            old[p_key] = ''.join([old.get(p_key, ''), p_value])
        elif p_type == p_schema.NUMBER:
            old[p_key] = old.get(p_key, 0) + p_value
        else:
            raise exception.InvalidMergeStrategyForParam(strategy=MERGE,
                                                         param=p_key)

    new_strategies = {}

    if not old:
        return new, new_strategies

    for key, value in new.items():
        # if key not in param_schemata ignore it
        if key in param_schemata and value is not None:
            param_merge_strategy = get_param_merge_strategy(
                strategies_in_file, key)
            if key not in available_strategies:
                new_strategies[key] = param_merge_strategy

            elif param_merge_strategy != available_strategies[key]:
                raise exception.ConflictingMergeStrategyForParam(
                    strategy=param_merge_strategy,
                    param=key, env_file=env_file)

            if param_merge_strategy == DEEP_MERGE:
                param_merge(key, value,
                            param_schemata[key],
                            deep_merge=True)
            elif param_merge_strategy == MERGE:
                param_merge(key, value, param_schemata[key])
            else:
                old[key] = value

    return old, new_strategies


def merge_environments(environment_files, files,
                       params, param_schemata):
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
    :type  params: dict
    :param param_schemata: parameter schema dict
    :type  param_schemata: dict
    """
    if not environment_files:
        return

    available_strategies = {}

    for filename in environment_files:
        raw_env = files[filename]
        parsed_env = env_fmt.parse(raw_env)
        strategies_in_file = parsed_env.pop(
            env_fmt.PARAMETER_MERGE_STRATEGIES, {})

        for section_key, section_value in parsed_env.items():
            if section_value:
                if section_key in (env_fmt.PARAMETERS,
                                   env_fmt.PARAMETER_DEFAULTS):
                    params[section_key], new_strategies = merge_parameters(
                        params[section_key], section_value,
                        param_schemata, strategies_in_file,
                        available_strategies, filename)
                    available_strategies.update(new_strategies)
                else:
                    params[section_key] = merge_map(params[section_key],
                                                    section_value)
