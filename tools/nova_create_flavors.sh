#!/bin/bash
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


# Nova rate limits actions so we need retry/sleep logic to avoid
# spurious failures when doing sequential operations
# we also sleep after every operation otherwise rate-limiting will definitely
# cause lots of failures
retry_cmd() {
    MAX_TRIES=5
    attempts=0
    while [[ ${attempts} < ${MAX_TRIES} ]]
    do
        attempts=$((${attempts} + 1))
        if ! $@ 2>/dev/null
        then
            echo "Command : \"$@\" failed, retry after 1s ${attempts}/${MAX_TRIES}"
            sleep 1
        else
            echo "$@ : OK"
            sleep 1
            break
        fi
    done

    if [[ ${attempts} == ${MAX_TRIES} ]]
    then
        echo "ERROR : persistent error attempting to run command \"$@\"!"
    fi
}


# Sanity-test nova flavor-list, this should catch problems with credentials
# or if nova is not running.  When calling from openstack install, it seems
# that nova gives 400 errors despite the service showing as active via
# systemctl, so we work around that by polling via retry_cmd before doing the
# final check - this should mean we wait for the service to come up but still
# exit if there is a non-transient problem
retry_cmd "nova flavor-list"
if ! nova flavor-list > /dev/null
then
    echo "ERROR, unable to do \"nova flavor-list\""
    echo "Check keystone credentials and that nova services are running"
    exit 1
fi

for f in $(nova flavor-list | grep "^| [0-9]" | awk '{print $2}')
do
    retry_cmd "nova flavor-delete $f"
done

retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 t1.micro 1 256 0 1"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.tiny 2 256 0 1"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.small 3 512 0 1"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.medium 4 768 0 1"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.large 5 1024 0 1"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m1.xlarge 6 2048 0 1"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m2.xlarge 7 2048 0 2"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m2.2xlarge 8 2048 0 2"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 m2.4xlarge 9 2048 0 2"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 c1.medium 10 2048 0 2"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 c1.xlarge 11 2048 0 2"
retry_cmd "nova flavor-create --ephemeral 10 --swap 0 --rxtx-factor 1 cc1.4xlarge 12 2048 0 2"

# Check we get the expected number of flavors on completion
num_flavors=$(nova flavor-list | grep "[0-9]. *|" | wc -l)
expected_flavors=12
if [[ ${num_flavors} != ${expected_flavors} ]]
then
    echo "ERROR : problem creating flavors, created ${num_flavors}, expected ${expected_flavors}"
fi
