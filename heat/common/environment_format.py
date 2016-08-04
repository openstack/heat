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
import yaml

from heat.common.i18n import _
from heat.common import template_format


SECTIONS = (
    PARAMETERS, RESOURCE_REGISTRY, PARAMETER_DEFAULTS,
    ENCRYPTED_PARAM_NAMES, EVENT_SINKS,
    PARAMETER_MERGE_STRATEGIES,
) = (
    'parameters', 'resource_registry', 'parameter_defaults',
    'encrypted_param_names', 'event_sinks',
    'parameter_merge_strategies',
)


def parse(env_str):
    """Takes a string and returns a dict containing the parsed structure."""
    if env_str is None:
        return {}

    try:
        env = template_format.yaml.load(env_str,
                                        Loader=template_format.yaml_loader)
    except yaml.YAMLError:
        # NOTE(prazumovsky): we need to return more informative error for
        # user, so use SafeLoader, which return error message with template
        # snippet where error has been occurred.
        try:
            env = yaml.load(env_str, Loader=yaml.SafeLoader)
        except yaml.YAMLError as yea:
            raise ValueError(yea)
    else:
        if env is None:
            env = {}

    if not isinstance(env, dict):
        raise ValueError(_('The environment is not a valid '
                           'YAML mapping data type.'))
    return validate(env)


def validate(env):
    for param in env:
        if param not in SECTIONS:
            raise ValueError(_('environment has wrong section "%s"') % param)
        if env[param] is None:
            raise ValueError(_('environment has empty section "%s"') % param)

    return env


def default_for_missing(env):
    """Checks a parsed environment for missing sections."""
    for param in SECTIONS:
        if param not in env and param != PARAMETER_MERGE_STRATEGIES:
            if param in (ENCRYPTED_PARAM_NAMES, EVENT_SINKS):
                env[param] = []
            else:
                env[param] = {}
