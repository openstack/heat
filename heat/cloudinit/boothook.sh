#!/bin/bash

# FIXME(shadower) this is a workaround for cloud-init 0.6.3 present in Ubuntu
# 12.04 LTS:
# https://bugs.launchpad.net/heat/+bug/1257410
#
# The old cloud-init doesn't create the users directly so the commands to do
# this are injected though nova_utils.py.
#
# Once we drop support for 0.6.3, we can safely remove this.
${add_custom_user}

# in case heat-cfntools has been installed from package but no symlinks
# are yet in /opt/aws/bin/
cfn-create-aws-symlinks

# Do not remove - the cloud boothook should always return success
exit 0
