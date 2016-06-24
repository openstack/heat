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

set -x

DEST=${DEST:-/opt/stack/new}

source $DEST/devstack/inc/ini-config

cd $DEST/heat/heat_integrationtests

# Register the flavors for booting test servers
iniset heat_integrationtests.conf DEFAULT instance_type m1.heat_int
iniset heat_integrationtests.conf DEFAULT minimal_instance_type m1.heat_micro
nova flavor-create m1.heat_int 452 512 0 1
nova flavor-create m1.heat_micro 453 128 0 1

# Register the glance image for testing
curl http://tarballs.openstack.org/heat-test-image/fedora-heat-test-image.qcow2 | glance image-create --name fedora-heat-test-image --disk-format qcow2 --container-format bare --visibility public
iniset heat_integrationtests.conf DEFAULT image_ref fedora-heat-test-image
iniset heat_integrationtests.conf DEFAULT boot_config_env $DEST/heat-templates/hot/software-config/boot-config/test_image_env.yaml
iniset heat_integrationtests.conf DEFAULT heat_config_notify_script $DEST/heat-templates/hot/software-config/elements/heat-config/bin/heat-config-notify
iniset heat_integrationtests.conf DEFAULT minimal_image_ref cirros-0.3.4-x86_64-uec
# admin creds already sourced, store in conf
iniset heat_integrationtests.conf DEFAULT admin_username $OS_USERNAME
iniset heat_integrationtests.conf DEFAULT admin_password $OS_PASSWORD

# Add functional tests to skip
iniset heat_integrationtests.conf DEFAULT skip_functional_test_list 'AutoScalingSignalTest.test_signal_during_suspend'

# Add scenario tests to skip
# VolumeBackupRestoreIntegrationTest skipped until failure rate can be reduced ref bug #1382300
iniset heat_integrationtests.conf DEFAULT skip_scenario_test_list 'SoftwareConfigIntegrationTest, VolumeBackupRestoreIntegrationTest'

cat heat_integrationtests.conf
