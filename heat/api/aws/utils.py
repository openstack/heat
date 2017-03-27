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

"""Helper utilities related to the AWS API implementations."""

import itertools
import re

from oslo_log import log as logging

from heat.api.aws import exception

LOG = logging.getLogger(__name__)


def format_response(action, response):
    """Format response from engine into API format."""
    return {'%sResponse' % action: {'%sResult' % action: response}}


def extract_param_pairs(params, prefix='', keyname='', valuename=''):
    """Extract user input params from AWS style parameter-pair encoded list.

    In the AWS API list items appear as two key-value
    pairs (passed as query parameters)  with keys of the form below:

    Prefix.member.1.keyname=somekey
    Prefix.member.1.keyvalue=somevalue
    Prefix.member.2.keyname=anotherkey
    Prefix.member.2.keyvalue=somevalue

    We reformat this into a dict here to match the heat
    engine API expected format.
    """
    plist = extract_param_list(params, prefix)
    kvs = [(p[keyname], p[valuename]) for p in plist
           if keyname in p and valuename in p]

    return dict(kvs)


def extract_param_list(params, prefix=''):
    """Extract a list-of-dicts based on parameters containing AWS style list.

    MetricData.member.1.MetricName=buffers
    MetricData.member.1.Unit=Bytes
    MetricData.member.1.Value=231434333
    MetricData.member.2.MetricName=buffers2
    MetricData.member.2.Unit=Bytes
    MetricData.member.2.Value=12345

    This can be extracted by passing prefix=MetricData, resulting in a
    list containing two dicts.
    """
    key_re = re.compile(r"%s\.member\.([0-9]+)\.(.*)" % (prefix))

    def get_param_data(params):
        for param_name, value in params.items():
            match = key_re.match(param_name)
            if match:
                try:
                    index = int(match.group(1))
                except ValueError:
                    pass
                else:
                    key = match.group(2)

                    yield (index, (key, value))

    # Sort and group by index
    def key_func(d):
        return d[0]

    data = sorted(get_param_data(params), key=key_func)
    members = itertools.groupby(data, key_func)

    return [dict(kv for di, kv in m) for mi, m in members]


def get_param_value(params, key):
    """Looks up an expected parameter in a parsed params dict.

    Helper function, looks up an expected parameter in a parsed
    params dict and returns the result.  If params does not contain
    the requested key we raise an exception of the appropriate type.
    """
    try:
        return params[key]
    except KeyError:
        LOG.error("Request does not contain %s parameter!", key)
        raise exception.HeatMissingParameterError(key)


def reformat_dict_keys(keymap=None, inputdict=None):
    """Utility function for mapping one dict format to another."""
    keymap = keymap or {}
    inputdict = inputdict or {}
    return dict([(outk, inputdict[ink]) for ink, outk in keymap.items()
                if ink in inputdict])
