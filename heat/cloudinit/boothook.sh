#!/bin/bash

# FIXME(shadower) The `useradd` and `sudoers` lines are a workaround for
# cloud-init 0.6.3 present in Ubuntu 12.04 LTS:
# https://bugs.launchpad.net/heat/+bug/1257410
# Once we drop support for it, we can safely remove them.
useradd -m @INSTANCE_USER@
echo -e '@INSTANCE_USER@\tALL=(ALL)\tNOPASSWD: ALL' >> /etc/sudoers

# in case heat-cfntools has been installed from package but no symlinks
# are yet in /opt/aws/bin/
cfn-create-aws-symlinks

# Do not remove - the cloud boothook should always return success
exit 0
