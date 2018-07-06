#!/bin/bash
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# This script creates required cloud resources and sets test options
# in heat_integrationtests.conf and in tempest.conf.
# Credentials are required for creating nova flavors and glance images.

set -e

CONF_DEST=${DEST:-/opt/stack/new}

source $DEST/devstack/inc/ini-config

set -x

function _config_iniset {
    local conf_file=$1

    source $TOP_DIR/openrc demo demo
    # user creds
    iniset $conf_file heat_plugin username $OS_USERNAME
    iniset $conf_file heat_plugin password $OS_PASSWORD
    iniset $conf_file heat_plugin project_name $OS_PROJECT_NAME
    iniset $conf_file heat_plugin auth_url $OS_AUTH_URL
    iniset $conf_file heat_plugin user_domain_id $OS_USER_DOMAIN_ID
    iniset $conf_file heat_plugin project_domain_id $OS_PROJECT_DOMAIN_ID
    iniset $conf_file heat_plugin user_domain_name $OS_USER_DOMAIN_NAME
    iniset $conf_file heat_plugin project_domain_name $OS_PROJECT_DOMAIN_NAME
    iniset $conf_file heat_plugin region $OS_REGION_NAME
    iniset $conf_file heat_plugin auth_version $OS_IDENTITY_API_VERSION

    local default_image_name=${DEFAULT_IMAGE_NAME:-cirros-0.3.6-x86_64-disk}

    # Register the flavors for booting test servers
    iniset $conf_file heat_plugin instance_type m1.heat_int
    iniset $conf_file heat_plugin minimal_instance_type m1.heat_micro

    iniset $conf_file heat_plugin image_ref Fedora-Cloud-Base-29-1.2.x86_64
    iniset $conf_file heat_plugin minimal_image_ref $default_image_name
    iniset $conf_file heat_plugin hidden_stack_tag hidden

    source $TOP_DIR/openrc admin admin
    iniset $conf_file heat_plugin admin_username $OS_USERNAME
    iniset $conf_file heat_plugin admin_password $OS_PASSWORD


    if [ "$DISABLE_CONVERGENCE" == "true" ]; then
        iniset $conf_file heat_plugin convergence_engine_enabled false
    fi
}


function _config_functionaltests
{
    local conf_file=$CONF_DEST/heat/heat_integrationtests/heat_integrationtests.conf
    _config_iniset $conf_file

    # Skip NotificationTest till bug #1721202 is fixed
    iniset $conf_file heat_plugin skip_functional_test_list 'NotificationTest'

    cat $conf_file
}

function _config_tempest_plugin
{
    local conf_file=$CONF_DEST/tempest/etc/tempest.conf
    iniset_multiline $conf_file service_available heat_plugin True
    _config_iniset $conf_file
    iniset $conf_file heat_plugin heat_config_notify_script $CONF_DEST/heat-agents/heat-config/bin/heat-config-notify
    iniset $conf_file heat_plugin boot_config_env $CONF_DEST/heat-templates/hot/software-config/boot-config/test_image_env.yaml

    # support test multi-cloud
    openstack application credential create heat_multicloud --secret secret --unrestricted
    app_cred_id=$(openstack application credential show heat_multicloud|grep ' id '|awk '{print $4}')
    export OS_CREDENTIAL_SECRET_ID=$(openstack secret store -n heat-multi-cloud-test-cred --payload '{"auth_type": "v3applicationcredential", "auth": {"auth_url": $OS_AUTH_URL, "application_credential_id": $app_cred_id, "application_credential_secret": "secret"}, "roles": ["admin"], "project_id": $app_cred_project_id}')
    iniset $conf_file heat_features_enabled multi_cloud True
    iniset $conf_file heat_plugin heat_plugin credential_secret_id $OS_CREDENTIAL_SECRET_ID

    # Skip SoftwareConfigIntegrationTest because it requires a custom image
    # Skip VolumeBackupRestoreIntegrationTest skipped until failure rate can be reduced ref bug #1382300
    # Skip AutoscalingLoadBalancerTest and AutoscalingLoadBalancerv2Test as deprecated neutron-lbaas service is not enabled
    iniset $conf_file heat_plugin skip_scenario_test_list 'AutoscalingLoadBalancerTest, AutoscalingLoadBalancerv2Test, \
        SoftwareConfigIntegrationTest'

    # Skip LoadBalancerv2Test as deprecated neutron-lbaas service is not enabled
    iniset $conf_file heat_plugin skip_functional_test_list 'LoadBalancerv2Test'

    # disable cinder backup feature
    iniset $conf_file volume-feature-enabled backup False

    cat $conf_file
}

_config_functionaltests
_config_tempest_plugin

# (FIXME) Remove this after backport to stable/rocky
# Remove/Recreate existing flavors
openstack flavor show m1.heat_int && openstack flavor delete m1.heat_int
openstack flavor show m1.heat_micro && openstack flavor delete m1.heat_micro

openstack flavor show m1.heat_int || openstack flavor create m1.heat_int --ram 512 --disk 4
openstack flavor show m1.heat_micro || openstack flavor create m1.heat_micro --ram 128 --disk 1
