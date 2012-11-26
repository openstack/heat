# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 - 2012 Justin Santa Barbara
# All Rights Reserved.
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

import base64
import hashlib
import hmac
import urllib

# FIXME : This should be imported from keystoneclient, so this can be removed
# when we no longer require an internal fallback implementation
# see : https://review.openstack.org/#/c/16964/
# https://blueprints.launchpad.net/keystone/+spec/ec2signer-to-keystoneclient


class Ec2Signer(object):
    """
    Utility class which adds allows a request to be signed with an AWS style
    signature, which can then be used for authentication via the keystone ec2
    authentication extension
    """

    def __init__(self, secret_key):
        secret_key = secret_key.encode()
        self.hmac = hmac.new(secret_key, digestmod=hashlib.sha1)
        if hashlib.sha256:
            self.hmac_256 = hmac.new(secret_key, digestmod=hashlib.sha256)

    def generate(self, credentials):
        """Generate auth string according to what SignatureVersion is given."""
        if credentials['params']['SignatureVersion'] == '0':
            return self._calc_signature_0(credentials['params'])
        if credentials['params']['SignatureVersion'] == '1':
            return self._calc_signature_1(credentials['params'])
        if credentials['params']['SignatureVersion'] == '2':
            return self._calc_signature_2(credentials['params'],
                                          credentials['verb'],
                                          credentials['host'],
                                          credentials['path'])
        raise Exception('Unknown Signature Version: %s' %
                        credentials['params']['SignatureVersion'])

    @staticmethod
    def _get_utf8_value(value):
        """Get the UTF8-encoded version of a value."""
        if not isinstance(value, str) and not isinstance(value, unicode):
            value = str(value)
        if isinstance(value, unicode):
            return value.encode('utf-8')
        else:
            return value

    def _calc_signature_0(self, params):
        """Generate AWS signature version 0 string."""
        s = params['Action'] + params['Timestamp']
        self.hmac.update(s)
        return base64.b64encode(self.hmac.digest())

    def _calc_signature_1(self, params):
        """Generate AWS signature version 1 string."""
        keys = params.keys()
        keys.sort(cmp=lambda x, y: cmp(x.lower(), y.lower()))
        for key in keys:
            self.hmac.update(key)
            val = self._get_utf8_value(params[key])
            self.hmac.update(val)
        return base64.b64encode(self.hmac.digest())

    def _calc_signature_2(self, params, verb, server_string, path):
        """Generate AWS signature version 2 string."""
        string_to_sign = '%s\n%s\n%s\n' % (verb, server_string, path)
        if self.hmac_256:
            current_hmac = self.hmac_256
            params['SignatureMethod'] = 'HmacSHA256'
        else:
            current_hmac = self.hmac
            params['SignatureMethod'] = 'HmacSHA1'
        keys = params.keys()
        keys.sort()
        pairs = []
        for key in keys:
            val = self._get_utf8_value(params[key])
            val = urllib.quote(val, safe='-_~')
            pairs.append(urllib.quote(key, safe='') + '=' + val)
        qs = '&'.join(pairs)
        string_to_sign += qs
        current_hmac.update(string_to_sign)
        b64 = base64.b64encode(current_hmac.digest())
        return b64
