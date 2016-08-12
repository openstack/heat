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

function _heat_set_user {
    OS_TENANT_NAME=$HEAT_PROJECT
    OS_PROJECT_NAME=$HEAT_PROJECT
    OS_USERNAME=$HEAT_USER
    OS_PASSWORD=$HEAT_PASS
}

function create {
    # run heat_integrationtests instead of tempest smoke before create
    pushd $BASE_DEVSTACK_DIR/../heat
    conf_file=heat_integrationtests/heat_integrationtests.conf
    iniset $conf_file heat_plugin username $OS_USERNAME
    iniset $conf_file heat_plugin password $OS_PASSWORD
    iniset $conf_file heat_plugin tenant_name $OS_PROJECT_NAME
    iniset $conf_file heat_plugin auth_url $OS_AUTH_URL
    iniset $conf_file heat_plugin user_domain_name $OS_USER_DOMAIN_NAME
    iniset $conf_file heat_plugin project_domain_name $OS_PROJECT_DOMAIN_NAME
    iniset $conf_file heat_plugin region $OS_REGION_NAME
    tox -eintegration heat_integrationtests.functional.test_create_update
    popd

    # creates a tenant for the server
    eval $(openstack project create -f shell -c id $HEAT_PROJECT)
    if [[ -z "$id" ]]; then
        die $LINENO "Didn't create $HEAT_PROJECT project"
    fi
    resource_save heat project_id $id

    # creates the user, and sets $id locally
    eval $(openstack user create $HEAT_USER \
            --project $id \
            --password $HEAT_PASS \
            -f shell -c id)
    if [[ -z "$id" ]]; then
        die $LINENO "Didn't create $HEAT_USER user"
    fi
    resource_save heat user_id $id
    _heat_set_user

    local stack_name='grenadine'
    resource_save heat stack_name $stack_name
    local loc=`dirname $BASH_SOURCE`
    heat stack-create -f $loc/templates/random_string.yaml $stack_name
}

function verify {
    _heat_set_user
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
        verify
        ;;
    "destroy")
        destroy
        ;;
esac
