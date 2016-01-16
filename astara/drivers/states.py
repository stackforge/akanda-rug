# Copyright (c) 2015 Akanda, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Reference states.

Each driver maps these to which ever neutron or other
services state.
"""
DOWN = 'down'
BOOTING = 'booting'
UP = 'up'
CONFIGURED = 'configured'
RESTART = 'restart'
REPLUG = 'replug'
GONE = 'gone'
ERROR = 'error'

# base list of ready states, driver can use its own list.
READY_STATES = (UP, CONFIGURED)


def internal(state_map, value):
    """Helper function to map service state back to astara internal state"""
    for k, v in state_map.items():
        if v == value:
            return k
    return GONE
