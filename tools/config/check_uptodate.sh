#!/bin/sh
TEMPDIR=`mktemp -d`
CFGFILE=heat.conf.sample
tools/config/generate_sample.sh -b ./ -p heat -o $TEMPDIR
if ! diff $TEMPDIR/$CFGFILE etc/heat/$CFGFILE
then
    echo "E: heat.conf.sample is not up to date, please run tools/config/generate_sample.sh"
    exit 42
fi
