# vim: tabstop=4 shiftwidth=4 softtabstop=4

#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import functools
import os
import sys
import base64
from lxml import etree
import re
import logging

from glance import client as glance_client
from heat.common import exception


SUCCESS = 0
FAILURE = 1


def catch_error(action):
    """Decorator to provide sensible default error handling for CLI actions."""
    def wrap(func):
        @functools.wraps(func)
        def wrapper(*arguments, **kwargs):
            try:
                ret = func(*arguments, **kwargs)
                return SUCCESS if ret is None else ret
            except exception.NotAuthorized:
                logging.error("Not authorized to make this request. Check " +\
                      "your credentials (OS_USERNAME, OS_PASSWORD, " +\
                      "OS_TENANT_NAME, OS_AUTH_URL and OS_AUTH_STRATEGY).")
                return FAILURE
            except exception.ClientConfigurationError:
                raise
            except Exception, e:
                options = arguments[0]
                if options.debug:
                    raise
                logging.error("Failed to %s. Got error:" % action)
                pieces = unicode(e).split('\n')
                for piece in pieces:
                    logging.error(piece)
                return FAILURE

        return wrapper
    return wrap


@catch_error('jeos-create')
def jeos_create(options, arguments, jeos_path, cfntools_path):
    '''
    Create a new JEOS (Just Enough Operating System) image.

    Usage: heat jeos-create <distribution> <architecture> <image type>

    Distribution: Distribution such as 'F16', 'F17', 'U10', 'D6'.
    Architecture: Architecture such as 'i386' 'i686' or 'x86_64'.
    Image Type: Image type such as 'gold' or 'cfntools'.
                'gold' is a basic gold JEOS.
                'cfntools' contains the cfntools helper scripts.

    The command must be run as root in order for libvirt to have permissions
    to create virtual machines and read the raw DVDs.
    '''

    # if not running as root, return EPERM to command line
    if os.geteuid() != 0:
        logging.error("jeos-create must be run as root")
        sys.exit(1)
    if len(arguments) < 3:
        print '\n  Please provide the distro, arch, and instance type.'
        print '  Usage:'
        print '   heat jeos-create <distro> <arch> <instancetype>'
        print '     instance type can be:'
        print '     gold builds a base image where userdata is used to' \
              ' initialize the instance'
        print '     cfntools builds a base image where AWS CloudFormation' \
              ' tools are present'
        sys.exit(1)

    distro = arguments.pop(0)
    arch = arguments.pop(0)
    instance_type = arguments.pop(0)
    images_dir = '/var/lib/libvirt/images'

    arches = ('x86_64', 'i386', 'amd64')
    arches_str = " | ".join(arches)
    instance_types = ('gold', 'cfntools')
    instances_str = " | ".join(instance_types)

    if not arch in arches:
        logging.error('arch %s not supported' % arch)
        logging.error('try: heat jeos-create %s [ %s ]' % (distro, arches_str))
        sys.exit(1)

    if not instance_type in instance_types:
        logging.error('A JEOS instance type of %s not supported' %\
            instance_type)
        logging.error('try: heat jeos-create %s %s [ %s ]' %\
            (distro, arch, instances_str))
        sys.exit(1)

    src_arch = 'i386'
    fedora_match = re.match('F(1[6-7])', distro)
    if fedora_match:
        if arch == 'x86_64':
            src_arch = 'x86_64'
        version = fedora_match.group(1)
        iso = '%s/Fedora-%s-%s-DVD.iso' % (images_dir, version, arch)
    elif distro == 'U10':
        if arch == 'amd64':
            src_arch = 'x86_64'
        iso = '%s/ubuntu-10.04.3-server-%s.iso' % (images_dir, arch)
    else:
        logging.error('distro %s not supported' % distro)
        logging.error('try: F16, F17 or U10')
        sys.exit(1)

    if not os.access(iso, os.R_OK):
        logging.error('*** %s does not exist.' % (iso))
        sys.exit(1)

    tdl_path = '%s%s-%s-%s-jeos.tdl' % (jeos_path, distro, arch, instance_type)
    if options.debug:
        print "Using tdl: %s" % tdl_path

    # Load the cfntools into the cfntool image by encoding them in base64
    # and injecting them into the TDL at the appropriate place
    if instance_type == 'cfntools':
        tdl_xml = etree.parse(tdl_path)
        cfn_tools = ['cfn-init', 'cfn-hup', 'cfn-signal', \
                    'cfn-get-metadata', 'cfn_helper.py']
        for cfnname in cfn_tools:
            f = open('%s/%s' % (cfntools_path, cfnname), 'r')
            cfscript_e64 = base64.b64encode(f.read())
            f.close()
            cfnpath = "/template/files/file[@name='/opt/aws/bin/%s']" % cfnname
            tdl_xml.xpath(cfnpath)[0].text = cfscript_e64

        # TODO(sdake) INSECURE
        tdl_xml.write('/tmp/tdl', xml_declaration=True)
        tdl_path = '/tmp/tdl'

    dsk_filename = '%s/%s-%s-%s-jeos.dsk' % (images_dir, distro,
                                             src_arch, instance_type)
    qcow2_filename = '%s/%s-%s-%s-jeos.qcow2' % (images_dir, distro,
                                                 arch, instance_type)
    image_name = '%s-%s-%s' % (distro, arch, instance_type)

    if not os.access(tdl_path, os.R_OK):
        logging.error('The tdl for that disto/arch is not available')
        sys.exit(1)

    creds = dict(username=options.username,
                 password=options.password,
                 tenant=options.tenant,
                 auth_url=options.auth_url,
                 strategy=options.auth_strategy)

    client = glance_client.Client(host="0.0.0.0", port=9292,
            use_ssl=False, auth_tok=None, creds=creds)

    parameters = {
        "filters": {},
        "limit": 10,
    }
    images = client.get_images(**parameters)

    image_registered = False
    for image in images:
        if image['name'] == distro + '-' + arch + '-' + instance_type:
            image_registered = True

    runoz = options.yes and 'y' or None
    if os.access(qcow2_filename, os.R_OK):
        while runoz not in ('y', 'n'):
            runoz = raw_input('An existing JEOS was found on disk.' \
                              ' Do you want to build a fresh JEOS?' \
                              ' (y/n) ').lower()
        if runoz == 'y':
            os.remove(qcow2_filename)
            os.remove(dsk_filename)
            if image_registered:
                client.delete_image(image['id'])
        elif runoz == 'n':
            answer = None
            while answer not in ('y', 'n'):
                answer = raw_input('Do you want to register your existing' \
                                   ' JEOS file with glance? (y/n) ').lower()
                if answer == 'n':
                    logging.info('No action taken')
                    sys.exit(0)
                elif answer == 'y' and image_registered:
                    answer = None
                    while answer not in ('y', 'n'):
                        answer = raw_input('Do you want to delete the ' \
                                           'existing JEOS in glance?' \
                                           ' (y/n) ').lower()
                    if answer == 'n':
                        logging.info('No action taken')
                        sys.exit(0)
                    elif answer == 'y':
                        client.delete_image(image['id'])

    if runoz == None or runoz == 'y':
        logging.info('Creating JEOS image (%s) - '\
                     'this takes approximately 10 minutes.' % image_name)
        extra_opts = ' '
        if options.debug:
            extra_opts = ' -d 3 '

        ozcmd = "oz-install %s -t 50000 -u %s -x /dev/null" % (extra_opts,
                                                               tdl_path)
        logging.debug("Running : %s" % ozcmd)
        res = os.system(ozcmd)
        if res == 256:
            sys.exit(1)
        if not os.access(dsk_filename, os.R_OK):
            logging.error('oz-install did not create the image,' \
                          ' check your oz installation.')
            sys.exit(1)

        logging.info('Converting raw disk image to a qcow2 image.')
        os.system("qemu-img convert -O qcow2 %s %s" % (dsk_filename,
                                                       qcow2_filename))

    logging.info('Registering JEOS image (%s) ' \
                 'with OpenStack Glance.' % image_name)

    image_meta = {'name': image_name,
                  'is_public': True,
                  'disk_format': 'qcow2',
                  'min_disk': 0,
                  'min_ram': 0,
                  'owner': options.username,
                  'container_format': 'bare'}

    try:
        with open(qcow2_filename) as ifile:
            image_meta = client.add_image(image_meta, ifile)
        image_id = image_meta['id']
        logging.debug(" Added new image with ID: %s" % image_id)
        logging.debug(" Returned the following metadata for the new image:")
        for k, v in sorted(image_meta.items()):
            logging.debug(" %(k)30s => %(v)s" % locals())
    except exception.ClientConnectionError, e:
        logging.error((" Failed to connect to the Glance API server." +\
               " Is the server running?" % locals()))
        pieces = unicode(e).split('\n')
        for piece in pieces:
            logging.error(piece)
            sys.exit(1)
    except Exception, e:
        logging.error(" Failed to add image. Got error:")
        pieces = unicode(e).split('\n')
        for piece in pieces:
            logging.error(piece)
        logging.warning(" Note: Your image metadata may still be in the " +\
               "registry, but the image's status will likely be 'killed'.")


class LazyPluggable(object):
    """A pluggable backend loaded lazily based on some value."""

    def __init__(self, pivot, **backends):
        self.__backends = backends
        self.__pivot = pivot
        self.__backend = None

    def __get_backend(self):
        if not self.__backend:
            backend_name = 'sqlalchemy'
            backend = self.__backends[backend_name]
            if isinstance(backend, tuple):
                name = backend[0]
                fromlist = backend[1]
            else:
                name = backend
                fromlist = backend

            self.__backend = __import__(name, None, None, fromlist)
        return self.__backend

    def __getattr__(self, key):
        backend = self.__get_backend()
        return getattr(backend, key)
