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
# in heat_integrationtests.conf.
# Credentials are required for creating nova flavors and glance images.

set -e

DEST=${DEST:-/opt/stack/new}

source $DEST/devstack/inc/ini-config

set -x

conf_file=$DEST/heat/heat_integrationtests/heat_integrationtests.conf

source $DEST/devstack/openrc demo demo
# user creds
iniset $conf_file heat_plugin username $OS_USERNAME
iniset $conf_file heat_plugin password $OS_PASSWORD
iniset $conf_file heat_plugin tenant_name $OS_PROJECT_NAME
iniset $conf_file heat_plugin auth_url $OS_AUTH_URL
iniset $conf_file heat_plugin user_domain_name $OS_USER_DOMAIN_NAME
iniset $conf_file heat_plugin project_domain_name $OS_PROJECT_DOMAIN_NAME
iniset $conf_file heat_plugin region $OS_REGION_NAME

source $DEST/devstack/openrc admin admin
iniset $conf_file heat_plugin admin_username $OS_USERNAME
iniset $conf_file heat_plugin admin_password $OS_PASSWORD

# Register the flavors for booting test servers
iniset $conf_file heat_plugin instance_type m1.heat_int
iniset $conf_file heat_plugin minimal_instance_type m1.heat_micro
openstack flavor create m1.heat_int --ram 512
openstack flavor create m1.heat_micro --ram 128

# Register the glance image for testing
curl -L https://download.fedoraproject.org/pub/fedora/linux/releases/24/CloudImages/x86_64/images/Fedora-Cloud-Base-24-1.2.x86_64.qcow2 | openstack image create fedora-heat-test-image --disk-format qcow2 --container-format bare --public
if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
   # The curl command failed, so the upload is mostly likely incorrect. Let's
   # bail out early.
   exit 1
fi

iniset $conf_file heat_plugin image_ref fedora-heat-test-image
iniset $conf_file heat_plugin boot_config_env $DEST/heat-templates/hot/software-config/boot-config/test_image_env.yaml
iniset $conf_file heat_plugin heat_config_notify_script $DEST/heat-templates/hot/software-config/elements/heat-config/bin/heat-config-notify
iniset $conf_file heat_plugin minimal_image_ref cirros-0.3.4-x86_64-uec

# Add scenario tests to skip
# VolumeBackupRestoreIntegrationTest skipped until failure rate can be reduced ref bug #1382300
iniset $conf_file heat_plugin skip_scenario_test_list 'SoftwareConfigIntegrationTest, VolumeBackupRestoreIntegrationTest'

cat $conf_file
