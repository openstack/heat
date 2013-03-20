#!/bin/bash
setenforce 0
useradd -m @INSTANCE_USER@
echo -e '@INSTANCE_USER@\tALL=(ALL)\tNOPASSWD: ALL' >> /etc/sudoers

# Do not remove - the cloud boothook should always return success
exit 0
