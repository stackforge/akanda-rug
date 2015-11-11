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

import time

from astara.test.functional import base


class TestAstaraRouter(base.AstaraFunctionalBase):
    @classmethod
    def setUpClass(cls):
        super(TestAstaraRouter, cls).setUpClass()
        cls.tenant = cls.get_tenant()
        cls.neutronclient = cls.tenant.clients.neutronclient

    def test_get_router_by_creating_a_net(self):
        """
        Test to ensure that in a clean tenant, when a network is created,
        /w an ipv6 subnet, a neutron router and an akanda router will be
        created as well.
        """
        network, router = self.tenant.setup_default_tenant_networking()
        self.assert_router_is_active(router['id'])

        # refresh router ref now that its active
        router = self.neutronclient.show_router(router['id'])['router']

        # for each subnet that was created during setup, ensure we have a
        # router interface added
        ports = self.neutronclient.list_ports()['ports']
        subnets = self.neutronclient.list_subnets(network_id=network['id'])
        subnets = subnets['subnets']
        self.assertEquals(len(ports), len(subnets))
        for port in ports:
            self.assertEquals(port['device_owner'], 'network:router_interface')
            self.assertEquals(port['device_id'], router['id'])
            self.assertEquals(
                sorted([subnet['id'] for subnet in subnets]),
                sorted([fip['subnet_id'] for fip in port['fixed_ips']])
            )

        self.ping_router_mgt_address(router['id'])

        # Ensure that if we destroy the nova instance, the RUG will rebuild
        # the router with a new instance.
        # This could live in a separate test case but it'd require the
        # above as setup, so just piggyback on it.

        old_server = self.get_router_appliance_server('router', router['id'])

        # NOTE(adam_g): In the gate, sometimes the appliance hangs on the
        # first config update and health checks get queued up behind the
        # hanging config update.  If thats the case, we need to wait a while
        # before deletion for the first to timeout.
        time.sleep(120)
        self.admin_clients.novaclient.servers.delete(old_server.id)

        # sleep for health_check_period (set by devstack)
        time.sleep(10)

        # look for the new server, retry giving rug time to do its thing.
        new_server = self.get_router_appliance_server(
            'rouer', router['id'], retries=60, wait_for_active=True)
        self.assertNotEqual(old_server.id, new_server.id)

        # routers report as ACTIVE initially (LP: #1491673)
        time.sleep(2)

        self.assert_router_is_active(router['id'])
        self.ping_router_mgt_address(router['id'])