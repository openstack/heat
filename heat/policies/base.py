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

from oslo_policy import policy

RULE_CONTEXT_IS_ADMIN = 'rule:context_is_admin'
RULE_PROJECT_ADMIN = 'rule:project_admin'
RULE_DENY_STACK_USER = 'rule:deny_stack_user'
RULE_DENY_EVERYBODY = 'rule:deny_everybody'
RULE_ALLOW_EVERYBODY = 'rule:allow_everybody'


rules = [
    policy.RuleDefault(
        name="context_is_admin",
        check_str="role:admin and is_admin_project:True",
        description="Decides what is required for the 'is_admin:True' check "
        "to succeed."),
    policy.RuleDefault(
        name="project_admin",
        check_str="role:admin",
        description="Default rule for project admin."),
    policy.RuleDefault(
        name="deny_stack_user",
        check_str="not role:heat_stack_user",
        description="Default rule for deny stack user."),
    policy.RuleDefault(
        name="deny_everybody",
        check_str="!",
        description="Default rule for deny everybody."),
    policy.RuleDefault(
        name="allow_everybody",
        check_str="",
        description="Default rule for allow everybody.")
]


def list_rules():
    return rules
