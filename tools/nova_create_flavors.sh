#!/bin/sh
# Create additional nova instance types (flavors)
# to map to the AWS instance types we have in the templates

# Default nova install (via tools/openstack) gives this:
# +----+-----------+-----------+------+-----------+------+-------+-------------+
# | ID |    Name   | Memory_MB | Disk | Ephemeral | Swap | VCPUs | RXTX_Factor |
# +----+-----------+-----------+------+-----------+------+-------+-------------+
# | 1  | m1.tiny   | 512       | 0    | 0         |      | 1     | 1.0         |
# | 2  | m1.small  | 2048      | 10   | 20        |      | 1     | 1.0         |
# | 3  | m1.medium | 4096      | 10   | 40        |      | 2     | 1.0         |
# | 4  | m1.large  | 8192      | 10   | 80        |      | 4     | 1.0         |
# | 5  | m1.xlarge | 16384     | 10   | 160       |      | 8     | 1.0         |
# +----+-----------+-----------+------+-----------+------+-------+-------------+

# Templates define these as valid
#      "t1.micro"    : { "Arch" : "32" },
#      "m1.small"    : { "Arch" : "32" },
#      "m1.large"    : { "Arch" : "64" },
#      "m1.xlarge"   : { "Arch" : "64" },
#      "m2.xlarge"   : { "Arch" : "64" },
#      "m2.2xlarge"  : { "Arch" : "64" },
#      "m2.4xlarge"  : { "Arch" : "64" },
#      "c1.medium"   : { "Arch" : "32" },
#      "c1.xlarge"   : { "Arch" : "64" },
#      "cc1.4xlarge" : { "Arch" : "64" }

# So for development purposes, we create all flavors, but with a maximum of
# 2vcpus, 10G disk and 2G RAM (since we're all running on laptops..)

for f in $(nova flavor-list | grep "^| [0-9]" | awk '{print $2}')
do
    nova flavor-delete $f
done

# Note, horrible sleep 1's are because nova starts failing requests due
# to rate limiting without them..
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 t1.micro 1 256 0 1
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.tiny 2 256 0 1
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.small 3 512 0 1
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.medium 4 768 0 1
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.large 5 1024 0 1
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.xlarge 6 2048 0 1
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m2.xlarge 7 2048 0 2
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m2.2xlarge 8 2048 0 2
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m2.4xlarge 9 2048 0 2
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 c1.medium 10 2048 0 2
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 c1.xlarge 11 2048 0 2
sleep 1
nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 cc1.4xlarge 12 2048 0 2
