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
#

import util
import nose
from nose.plugins.attrib import attr


@attr(speed='slow')
@attr(tag=['func', 'wordpress'])
def test_template():
    try:
        template = 'WordPress_Single_Instance.template'

        func_utils = util.FuncUtils()

        func_utils.prepare_jeos('F17', 'x86_64', 'cfntools')
        func_utils.create_stack(template, 'F17')
        func_utils.check_cfntools()
        func_utils.wait_for_provisioning()
        func_utils.check_user_data(template)

        ssh = func_utils.get_ssh_client()

        # ensure wordpress was installed
        wp_file = '/etc/wordpress/wp-config.php'
        stdin, stdout, sterr = ssh.exec_command('ls ' + wp_file)
        result = stdout.readlines().pop().rstrip()
        assert result == wp_file
        print "Wordpress installation detected"
    finally:
        func_utils.cleanup()
