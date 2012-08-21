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

'''
Helper utilities related to the AWS API implementations
'''

import re


def format_response(action, response):
    """
    Format response from engine into API format
    """
    return {'%sResponse' % action: {'%sResult' % action: response}}


def extract_user_params(params):
    """
    Extract a dictionary of user input parameters for the stack

    In the AWS API parameters, each user parameter appears as two key-value
    pairs with keys of the form below:

    Parameters.member.1.ParameterKey
    Parameters.member.1.ParameterValue

    We reformat this into a normal dict here to match the heat
    engine API expected format

    Note this implemented outside of "create" as it will also be
    used by update (and EstimateTemplateCost if appropriate..)
    """
    # Define the AWS key format to extract
    PARAM_KEYS = (
    PARAM_USER_KEY_re,
    PARAM_USER_VALUE_fmt,
    ) = (
    re.compile(r'Parameters\.member\.(.*?)\.ParameterKey$'),
    'Parameters.member.%s.ParameterValue',
    )

    def get_param_pairs():
        for k in params:
            keymatch = PARAM_USER_KEY_re.match(k)
            if keymatch:
                key = params[k]
                v = PARAM_USER_VALUE_fmt % keymatch.group(1)
                try:
                    value = params[v]
                except KeyError:
                    logger.error('Could not apply parameter %s' % key)

                yield (key, value)

    return dict(get_param_pairs())


def reformat_dict_keys(keymap={}, inputdict={}):
    '''
    Utility function for mapping one dict format to another
    '''
    result = {}
    for key in keymap:
        result[keymap[key]] = inputdict[key]
    return result
