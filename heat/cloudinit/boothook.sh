#!/bin/bash

# in case heat-cfntools has been installed from package but no symlinks
# are yet in /opt/aws/bin/
cfn-create-aws-symlinks

# Do not remove - the cloud boothook should always return success
exit 0
