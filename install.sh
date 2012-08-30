#!/bin/bash

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

CONF_DIR=/etc/heat
LOG_DIR=/var/log/heat

mkdir -p $LOG_DIR
mkdir -p $CONF_DIR

pushd etc > /dev/null

# Archive existing heat-api* config files in preparation
# for change to heat-api-cfn*, and future use of heat-api*
# the OpenStack API
for ext in '.conf' '-paste.ini'; do
    heat_api_file="${CONF_DIR}/heat-api${ext}"
    if [ -e ${heat_api_file} ]; then
        echo "archiving configuration file ${heat_api_file}"
        mv $heat_api_file ${heat_api_file}.bak
    fi
done

for f in *
do
    if [ -d $f ]; then
        # ignore directories
        continue
    elif [ -f $CONF_DIR/$f ]; then
        echo "not copying over $CONF_DIR/$f"
        diff -u $CONF_DIR/$f $f
    elif [ $f = 'heat-engine.conf' ]; then
	cat $f | sed s/%ENCRYPTION_KEY%/`hexdump -n 16 -v -e '/1 "%02x"' /dev/random`/ > $CONF_DIR/$f
    else
        cp $f $CONF_DIR
    fi
done
popd > /dev/null

./setup.py install >/dev/null
rm -rf build heat.egg-info

