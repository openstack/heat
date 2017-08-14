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
# in tempest.conf.

set -e

DEST=${DEST:-/opt/stack/new}

source $DEST/devstack/inc/ini-config

set -x

conf_file=$DEST/tempest/etc/tempest.conf

iniset_multiline $conf_file service_available heat_plugin True

source $DEST/devstack/openrc demo demo
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

source $DEST/devstack/openrc admin admin
iniset $conf_file heat_plugin admin_username $OS_USERNAME
iniset $conf_file heat_plugin admin_password $OS_PASSWORD


# Register the flavors for booting test servers
iniset $conf_file heat_plugin instance_type m1.heat_int
iniset $conf_file heat_plugin minimal_instance_type m1.heat_micro
openstack flavor create m1.heat_int --ram 512
openstack flavor create m1.heat_micro --ram 128

iniset $conf_file heat_plugin image_ref Fedora-Cloud-Base-26-1.5.x86_64
iniset $conf_file heat_plugin boot_config_env $DEST/heat-templates/hot/software-config/boot-config/test_image_env.yaml
iniset $conf_file heat_plugin heat_config_notify_script $DEST/heat-templates/hot/software-config/elements/heat-config/bin/heat-config-notify
iniset $conf_file heat_plugin minimal_image_ref cirros-0.3.5-x86_64-disk

# Skip test_cancel_update_server_with_port till bug #1607714 is fixed in nova
# Skip ReloadOnSighupTest. Most jobs now run with apache+uwsgi, so the test has no significance
iniset $conf_file heat_plugin skip_functional_test_list 'CancelUpdateTest.test_cancel_update_server_with_port, ReloadOnSighupTest, StackSnapshotRestoreTest'

# Add scenario tests to skip
# VolumeBackupRestoreIntegrationTest skipped until failure rate can be reduced ref bug #1382300
# test_server_signal_userdata_format_software_config is skipped untill bug #1651768 is resolved
# StackSnapshotRestoreTest skipped until bug #1694371 is resolved
iniset $conf_file heat_plugin skip_scenario_test_list 'SoftwareConfigIntegrationTest, VolumeBackupRestoreIntegrationTest'

cat $conf_file
