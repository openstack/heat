#!/usr/bin/python

import eventlet
from eventlet.green import socket
import libssh2
import time
import os
import random
import base64
import uuid
import M2Crypto
from novaclient.v1_1 import client

def instance_start(instance_name, image_name, flavor_name):
    """
    Method to start an instance
    """
    def _null_callback(p, n, out):
        """
        Method to silence the default M2Crypto.RSA.gen_key output.
        """
        pass

    private_key = M2Crypto.RSA.gen_key(2048, 65537, _null_callback)

    # this is the binary public key, in ssh "BN" (BigNumber) MPI format.
    # The ssh BN MPI format consists of 4 bytes that describe the length
    # of the following data, followed by the data itself in big-endian
    # format.  The start of the string is 0x0007, which represent the 7
    # bytes following that make up 'ssh-rsa'.  The key exponent and
    # modulus as fetched out of M2Crypto are already in MPI format, so
    # we can just use them as-is.  We then have to base64 encode the
    # result, add a little header information, and then we have a
    # full public key.
    username = os.environ['OS_USERNAME']
    password = os.environ['OS_PASSWORD']
    tenant = os.environ['OS_TENANT_NAME']
    auth_url = os.environ['OS_AUTH_URL']
    nova_client = client.Client(username, password, tenant, auth_url, service_type='compute', service_name='nova')
    public_key_bn = '\x00\x00\x00\x07' + 'ssh-rsa' + private_key.e + private_key.n
    public_key = 'ssh-rsa %s support@heat-api.org\n' % (base64.b64encode(public_key_bn))
    private_key.save_key('/tmp/private_key', cipher=None)
    random_uuid = uuid.uuid4()
    key_uuid = uuid.uuid3(random_uuid, '%s %s %s' % (instance_name, image_name, flavor_name))
    nova_client.keypairs.create(str(key_uuid), public_key)

    image_list = nova_client.images.list()
    for o in image_list:
        if getattr(o, 'name', '') == image_name:
            image_id = o.id #getattr(o, 'id', '')

    flavor_list = nova_client.flavors.list()
    for o in flavor_list:
        if getattr(o, 'name', '') == flavor_name:
            flavor_id = getattr(o, 'id', '')

    nova_client.servers.create(name=instance_name, image=image_id,
	flavor=flavor_id, key_name=str(key_uuid))

    return private_key

instance_start('instance-F16-test', 'F16-x86_64', "m1.tiny")

