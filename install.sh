#!/bin/bash

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root" >&2
    exit 1
fi

# Install prefix for config files (e.g. "/usr/local").
# Leave empty to install into /etc
CONF_PREFIX=""
LOG_DIR=/var/log/heat


install -d $LOG_DIR

detect_rabbit() {
   PKG_CMD="rpm -q"
   RABBIT_PKG="rabbitmq-server"
   QPID_PKG="qpid-cpp-server"

    # Detect OS type
    # Ubuntu has an lsb_release command which allows us to detect if it is Ubuntu
    if lsb_release -i 2>/dev/null | grep -iq ubuntu
    then
        PKG_CMD="dpkg -s"
        QPID_PKG="qpidd"
    fi
    if $PKG_CMD $RABBIT_PKG > /dev/null 2>&1
    then
        if ! $PKG_CMD $QPID_PKG > /dev/null 2>&1
        then
            return 0
        fi
    fi
    return 1
}

# Determinate is the given option present in the INI file
# ini_has_option config-file section option
function ini_has_option() {
    local file=$1
    local section=$2
    local option=$3
    local line
    line=$(sed -ne "/^\[$section\]/,/^\[.*\]/ { /^$option[ \t]*=/ p; }" "$file")
    [ -n "$line" ]
}

# Set an option in an INI file
# iniset config-file section option value
function iniset() {
    local file=$1
    local section=$2
    local option=$3
    local value=$4
    if ! grep -q "^\[$section\]" "$file"; then
        # Add section at the end
        echo -e "\n[$section]" >>"$file"
    fi
    if ! ini_has_option "$file" "$section" "$option"; then
        # Add it
        sed -i -e "/^\[$section\]/ a\\
$option = $value
" "$file"
    else
        # Replace it
        sed -i -e "/^\[$section\]/,/^\[.*\]/ s|^\($option[ \t]*=[ \t]*\).*$|\1$value|" "$file"
    fi
}

basic_configuration() {
    conf_path=$1
    if echo $conf_path | grep ".conf$" >/dev/null 2>&1
    then
        iniset $target DEFAULT auth_encryption_key `hexdump -n 16 -v -e '/1 "%02x"' /dev/random`
        iniset $target database connection "mysql+pymysql://heat:heat@localhost/heat"

        BRIDGE_IP=127.0.0.1
        iniset $target DEFAULT heat_metadata_server_url "http://${BRIDGE_IP}:8000/"

        if detect_rabbit
        then
            echo "rabbitmq detected, configuring $conf_path for rabbit" >&2
            iniset $conf_path DEFAULT rpc_backend kombu
            iniset $conf_path oslo_messaging_rabbit rabbit_password guest
        else
            echo "qpid detected, configuring $conf_path for qpid" >&2
            iniset $conf_path DEFAULT rpc_backend qpid
        fi
    fi
}

install_dir() {
    local dir=$1
    local prefix=$2

    for fn in $(ls $dir); do
        f=$dir/$fn
        target=$prefix/$f
        if [ $fn = 'heat.conf.sample' ]; then
            target=$prefix/$dir/heat.conf
        fi
        if [ -d $f ]; then
            [ -d $target ] || install -d $target
            install_dir $f $prefix
        elif [ -f $target ]; then
            echo "NOT replacing existing config file $target" >&2
            diff -u $target $f
        else
            echo "Installing $fn in $prefix/$dir" >&2
            install -m 664 $f $target
            if [ $fn = 'heat.conf.sample' ]; then
                basic_configuration $target
            fi
        fi
    done
}

install_dir etc $CONF_PREFIX

python setup.py install >/dev/null
rm -rf build heat.egg-info
