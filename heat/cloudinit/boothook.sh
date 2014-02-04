#!/bin/bash
command -v setenforce >/dev/null 2>&1 && setenforce 0
useradd -m @INSTANCE_USER@
echo -e '@INSTANCE_USER@\tALL=(ALL)\tNOPASSWD: ALL' >> /etc/sudoers

# in case heat-cfntools has been installed from package but no symlinks
# are yet in /opt/aws/bin/
cfn-create-aws-symlinks

# Do not remove - the cloud boothook should always return success
exit 0
