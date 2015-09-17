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
import six

from oslo.utils import timeutils


class CooldownMixin(object):
    '''
    Utility class to encapsulate Cooldown related logic which is shared
    between AutoScalingGroup and ScalingPolicy. This logic includes both
    cooldown timestamp comparing and scaling in progress checking.
    '''
    def _cooldown_inprogress(self):
        inprogress = False
        try:
            # Negative values don't make sense, so they are clamped to zero
            cooldown = max(0, self.properties[self.COOLDOWN])
        except TypeError:
            # If not specified, it will be None, same as cooldown == 0
            cooldown = 0

        metadata = self.metadata_get()
        if metadata.get('scaling_in_progress'):
            return True

        if 'cooldown' not in metadata:
            # Note: this is for supporting old version cooldown checking
            if metadata and cooldown != 0:
                last_adjust = next(six.iterkeys(metadata))
                if not timeutils.is_older_than(last_adjust, cooldown):
                    inprogress = True
        elif cooldown != 0:
            last_adjust = next(six.iterkeys(metadata['cooldown']))
            if not timeutils.is_older_than(last_adjust, cooldown):
                inprogress = True

        if not inprogress:
            metadata['scaling_in_progress'] = True
            self.metadata_set(metadata)

        return inprogress

    def _cooldown_timestamp(self, reason):
        # Save cooldown timestamp into metadata and clean the
        # scaling_in_progress state.
        # If we wanted to implement the AutoScaling API like AWS does,
        # we could maintain event history here, but since we only need
        # the latest event for cooldown, just store that for now
        metadata = self.metadata_get()
        if reason is not None:
            metadata['cooldown'] = {timeutils.utcnow().isoformat(): reason}
        metadata['scaling_in_progress'] = False
        self.metadata_set(metadata)
