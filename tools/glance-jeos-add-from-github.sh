#!/bin/bash
# Downloads JEOS images from github and installs them in glance

DISK_FORMAT="qcow2"
INDEX_URL="https://github.com/heat-api/prebuilt-jeos-images/downloads"
DOWNLOAD_URL="http://cloud.github.com/downloads/heat-api/prebuilt-jeos-images"
IMAGES=$(curl -s ${INDEX_URL} | grep 'href="/downloads/heat-api/prebuilt-jeos-images' 2>/dev/null | grep ${DISK_FORMAT} | cut -d">" -f2 | cut -d"<" -f1)

for i in ${IMAGES}
do
    NAME=$(echo $i | sed "s/\.${DISK_FORMAT}//")
    echo "Downloading and registering $i with OpenStack glance as ${NAME}"
    echo "Downloading from ${DOWNLOAD_URL}/$i"
    glance add name=${NAME} is_public=true disk_format=${DISK_FORMAT} container_format=bare copy_from="${DOWNLOAD_URL}/$i"
done
