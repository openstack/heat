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

# Check strings that embody common personas
SYSTEM_ADMIN = 'role:admin and system_scope:all'
SYSTEM_READER = 'role:reader and system_scope:all'
PROJECT_MEMBER = 'role:member and project_id:%(project_id)s'
PROJECT_READER = 'role:reader and project_id:%(project_id)s'

# Heat personas
PROJECT_ADMIN = 'role:admin and project_id:%(project_id)s'
PROJECT_STACK_USER = 'role:heat_stack_user and project_id:%(project_id)s'

# Composite check strings that are useful for policies that protect APIs that
# operate at different scopes.
SYSTEM_ADMIN_OR_PROJECT_MEMBER = (
    '(' + SYSTEM_ADMIN + ')'
    ' or (' + PROJECT_MEMBER + ')'
)
SYSTEM_OR_PROJECT_READER = (
    '(' + SYSTEM_READER + ')'
    ' or (' + PROJECT_READER + ')'
)
SYSTEM_ADMIN_OR_PROJECT_MEMBER_OR_STACK_USER = (
    '(' + SYSTEM_ADMIN + ')'
    ' or (' + PROJECT_MEMBER + ')'
    ' or (' + PROJECT_STACK_USER + ')'
)
SYSTEM_OR_PROJECT_READER_OR_STACK_USER = (
    '(' + SYSTEM_READER + ')'
    ' or (' + PROJECT_READER + ')'
    ' or (' + PROJECT_STACK_USER + ')'
)


rules = [
    policy.RuleDefault(
        name="context_is_admin",
        check_str=(
            "(role:admin and is_admin_project:True) OR "
            "(" + SYSTEM_ADMIN + ")"
        ),
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
