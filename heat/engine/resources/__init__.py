
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

from heat.engine import environment
from heat.engine import plugin_manager


def _register_resources(env, type_pairs):
    for res_name, res_class in type_pairs:
        env.register_class(res_name, res_class)


def _register_constraints(env, type_pairs):
    for constraint_name, constraint in type_pairs:
        env.register_constraint(constraint_name, constraint)


_environment = None


def global_env():
    if _environment is None:
        initialise()
    return _environment


def initialise():
    global _environment
    if _environment is not None:
        return

    global_env = environment.Environment({}, user_env=False)
    _load_global_environment(global_env)
    _environment = global_env


def _load_global_environment(env):
    _load_global_resources(env)
    environment.read_global_environment(env)


def _load_global_resources(env):
    manager = plugin_manager.PluginManager(__name__)

    # Sometimes resources should not be available for registration in Heat due
    # to unsatisfied dependencies. We look first for the function
    # 'available_resource_mapping', which should return the filtered resources.
    # If it is not found, we look for the legacy 'resource_mapping'.
    resource_mapping = plugin_manager.PluginMapping(['available_resource',
                                                     'resource'])
    constraint_mapping = plugin_manager.PluginMapping('constraint')

    _register_resources(env, resource_mapping.load_all(manager))
    _register_constraints(env, constraint_mapping.load_all(manager))
