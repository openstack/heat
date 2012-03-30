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

import anydbm
import json

def raw_template_get(context, template_id):
    return 'test return value'

def raw_template_get_all(context):
    pass

def raw_template_create(context, values):
    pass


def parsed_template_get(context, template_id):
    pass

def parsed_template_get_all(context):
    pass

def parsed_template_create(context, values):
    pass


def state_get(context, state_id):
    pass

def state_get_all(context):
    pass

def state_create(context, values):
    pass


def event_get(context, event_id):
    pass

def event_get_all(context):
    pass

def event_get_all_by_stack(context, stack_id):
    events = {'events': []}
    try:
        d = anydbm.open('/var/lib/heat/%s.events.db' % stack_id, 'r')
    except:
        return events

    for k, v in d.iteritems():
        if k != 'lastid':
            events['events'].append(json.loads(v))

    d.close()
    return events

def event_create(context, event):
    '''
    EventId	The unique ID of this event.
    Timestamp	Time the status was updated.
    '''
    name = event['StackName']
    d = anydbm.open('/var/lib/heat/%s.events.db' % name, 'c')
    if d.has_key('lastid'):
        newid = int(d['lastid']) + 1
    else:
        newid = 1
    event['EventId'] = '%d' % newid
    d['lastid'] = event['EventId']
    d[event['EventId']] = json.dumps(event)

    d.close()

