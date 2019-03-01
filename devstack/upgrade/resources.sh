#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

set -o errexit

source $GRENADE_DIR/grenaderc
source $GRENADE_DIR/functions

source $TOP_DIR/openrc admin admin
source $TOP_DIR/inc/ini-config

set -o xtrace

HEAT_USER=heat_grenade
HEAT_PROJECT=heat_grenade
HEAT_PASS=pass
DEFAULT_DOMAIN=default

function _heat_set_user {
    OS_TENANT_NAME=$HEAT_PROJECT
    OS_PROJECT_NAME=$HEAT_PROJECT
    OS_USERNAME=$HEAT_USER
    OS_PASSWORD=$HEAT_PASS
    OS_USER_DOMAIN_ID=$DEFAULT_DOMAIN
    OS_PROJECT_DOMAIN_ID=$DEFAULT_DOMAIN
}

function _write_heat_integrationtests {
    local upgrade_tests=$1
    cat > $upgrade_tests <<EOF
heat_tempest_plugin.tests.api
heat_integrationtests.functional.test_autoscaling
heat_integrationtests.functional.test_cancel_update
heat_integrationtests.functional.test_create_update
heat_integrationtests.functional.test_instance_group
heat_integrationtests.functional.test_resource_group.ResourceGroupTest
heat_integrationtests.functional.test_resource_group.ResourceGroupUpdatePolicyTest
heat_integrationtests.functional.test_software_deployment_group
heat_integrationtests.functional.test_validation
heat_tempest_plugin.tests.functional.test_software_config.ParallelDeploymentsTest
heat_tempest_plugin.tests.functional.test_nova_server_networks
EOF
}

function _run_heat_integrationtests {
    local devstack_dir=$1

    pushd $devstack_dir/../tempest
    export DEST=$(dirname $devstack_dir)
    $DEST/heat/heat_integrationtests/prepare_test_env.sh
    $DEST/heat/heat_integrationtests/prepare_test_network.sh

    # Run set of specified functional tests
    UPGRADE_TESTS=upgrade_tests.list
    _write_heat_integrationtests $UPGRADE_TESTS

    tox -evenv-tempest -- stestr --test-path=$DEST/heat/heat_integrationtests --top-dir=$DEST/heat \
        --group_regex='heat_tempest_plugin\.tests\.api\.test_heat_api[._]([^_]+)' \
        run --whitelist-file $UPGRADE_TESTS
    _heat_set_user
    popd
}

function create {
    if [ "${RUN_HEAT_INTEGRATION_TESTS}" == "True" ]; then
        # run heat integration tests instead of tempest smoke before create
        _run_heat_integrationtests $BASE_DEVSTACK_DIR
    fi

    source $TOP_DIR/openrc admin admin
    # creates a tenant for the server
    eval $(openstack project create -f shell -c id $HEAT_PROJECT)
    if [[ -z "$id" ]]; then
        die $LINENO "Didn't create $HEAT_PROJECT project"
    fi
    resource_save heat project_id $id
    local project_id=$id

    # creates the user, and sets $id locally
    eval $(openstack user create $HEAT_USER \
            --project $id \
            --password $HEAT_PASS \
            -f shell -c id)
    if [[ -z "$id" ]]; then
        die $LINENO "Didn't create $HEAT_USER user"
    fi
    resource_save heat user_id $id
    # with keystone v3 user created in a project is not assigned a role
    # https://bugs.launchpad.net/keystone/+bug/1662911
    openstack role add Member --user $id --project $project_id

    _heat_set_user

    local stack_name='grenadine'
    resource_save heat stack_name $stack_name
    local loc=`dirname $BASH_SOURCE`
    heat stack-create -f $loc/templates/random_string.yaml $stack_name
}

function verify {
    _heat_set_user
    local side="$1"
    if [[ "$side" = "post-upgrade" ]]; then
        if [ "${RUN_HEAT_INTEGRATION_TESTS}" == "True" ]; then
            _run_heat_integrationtests $TARGET_DEVSTACK_DIR
        fi
    fi
    stack_name=$(resource_get heat stack_name)
    heat stack-show $stack_name
    # TODO(sirushtim): Create more granular checks for Heat.
}

function verify_noapi {
    # TODO(sirushtim): Write tests to validate liveness of the resources
    # it creates during possible API downtime.
    :
}

function destroy {
    _heat_set_user
    heat stack-delete $(resource_get heat stack_name)

    source $TOP_DIR/openrc admin admin
    local user_id=$(resource_get heat user_id)
    local project_id=$(resource_get heat project_id)
    openstack user delete $user_id
    openstack project delete $project_id
}

# Dispatcher
case $1 in
    "create")
        create
        ;;
    "verify_noapi")
        verify_noapi
        ;;
    "verify")
        verify $2
        ;;
    "destroy")
        destroy
        ;;
esac
