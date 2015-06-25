# Copyright 2014 DreamHost, LLC
#
# Author: DreamHost, LLC
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


import logging
from collections import deque

import mock
import unittest2 as unittest

from akanda.rug import event
from akanda.rug import state
from akanda.rug import instance_manager
from akanda.rug.api.neutron import RouterGone


class BaseTestStateCase(unittest.TestCase):
    state_cls = state.State

    def setUp(self):
        self.ctx = mock.Mock()  # worker context
        log = logging.getLogger(__name__)
        instance_mgr_cls = \
            mock.patch('akanda.rug.instance_manager.InstanceManager').start()
        self.addCleanup(mock.patch.stopall)
        self.instance = instance_mgr_cls.return_value
        self.params = state.StateParams(
            instance=self.instance,
            log=log,
            queue=deque(),
            bandwidth_callback=mock.Mock(),
            reboot_error_threshold=3,
            router_image_uuid='GLANCE-IMAGE-123'
        )
        self.state = self.state_cls(self.params)

    def _test_transition_hlpr(self, action, expected_class,
                              instance_state=state.instance_manager.UP):
        self.instance.state = instance_state
        result = self.state.transition(action, self.ctx)
        self.assertIsInstance(result, expected_class)
        return result


class TestBaseState(BaseTestStateCase):
    def test_execute(self):
        self.assertEqual(
            self.state.execute('action', self.ctx),
            'action'
        )

    def test_transition(self):
        self.assertEqual(
            self.state.transition('action', self.ctx),
            self.state
        )


class TestCalcActionState(BaseTestStateCase):
    state_cls = state.CalcAction

    def _test_hlpr(self, expected_action, queue_states,
                   leftover=0, initial_action=event.POLL):
        self.params.queue = deque(queue_states)
        self.assertEqual(
            self.state.execute(initial_action, self.ctx),
            expected_action
        )
        self.assertEqual(len(self.params.queue), leftover)

    def test_execute_empty_queue(self):
        self._test_hlpr('testaction', [], initial_action='testaction')

    def test_execute_delete_in_queue(self):
        self._test_hlpr(event.DELETE, [event.CREATE, event.DELETE], 2)

    def test_none_start_action_update(self):
        self._test_hlpr(expected_action=event.UPDATE,
                        queue_states=[event.UPDATE, event.UPDATE],
                        leftover=0,
                        initial_action=None)

    def test_none_start_action_poll(self):
        self._test_hlpr(expected_action=event.POLL,
                        queue_states=[event.POLL, event.POLL],
                        leftover=0,
                        initial_action=None)

    def test_execute_ignore_pending_update_follow_create(self):
        self._test_hlpr(event.CREATE, [event.CREATE, event.UPDATE])

    def test_execute_upgrade_to_create_follow_update(self):
        self._test_hlpr(event.CREATE, [event.UPDATE, event.CREATE])

    def test_execute_collapse_same_events(self):
        events = [event.UPDATE, event.UPDATE, event.UPDATE]
        self._test_hlpr(event.UPDATE, events, 0)

    def test_execute_collapse_mixed_events(self):
        events = [
            event.UPDATE,
            event.POLL,
            event.UPDATE,
            event.POLL,
            event.UPDATE,
            event.READ,
        ]
        self._test_hlpr(event.UPDATE, events, 1)

    def test_execute_events_ending_with_poll(self):
        events = [
            event.UPDATE,
            event.UPDATE,
            event.POLL,
            event.POLL,
        ]
        self._test_hlpr(event.UPDATE, events, 0)

    def test_transition_update_missing_router_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.UPDATE,
            state.CheckBoot,
            instance_manager.BOOTING
        )

    def test_transition_update_missing_router_not_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.UPDATE,
            state.CheckBoot,
            instance_manager.BOOTING
        )

    def test_transition_delete_missing_router_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.DELETE,
            state.StopInstance,
            instance_manager.DOWN
        )

    def test_transition_delete_missing_router_not_down(self):
        self.ctx.neutron = mock.Mock()
        self.ctx.neutron.get_router_detail.side_effect = RouterGone
        self._test_transition_hlpr(
            event.DELETE,
            state.StopInstance,
            instance_manager.BOOTING
        )

    def test_transition_delete_down_instance(self):
        self._test_transition_hlpr(event.DELETE, state.StopInstance, instance_manager.DOWN)

    def test_transition_delete_up_instance(self):
        self._test_transition_hlpr(event.DELETE, state.StopInstance)

    def test_transition_create_down_instance(self):
        for evt in [event.POLL, event.READ, event.UPDATE, event.CREATE]:
            self._test_transition_hlpr(evt, state.CreateInstance, instance_manager.DOWN)

    def test_transition_poll_up_instance(self):
        self._test_transition_hlpr(event.POLL, state.Alive, instance_manager.UP)

    def test_transition_poll_configured_instance(self):
        self._test_transition_hlpr(
            event.POLL,
            state.Alive,
            instance_manager.CONFIGURED
        )

    def test_transition_other_up_instance(self):
        for evt in [event.READ, event.UPDATE, event.CREATE]:
            self._test_transition_hlpr(evt, state.Alive)

    def test_transition_update_error_instance(self):
        self.instance.error_cooldown = False
        result = self._test_transition_hlpr(
            event.UPDATE,
            state.ClearError,
            instance_manager.ERROR,
        )
        self.assertIsInstance(result._next_state, state.Alive)

    def test_transition_update_error_instance_in_error_cooldown(self):
        self.instance.error_cooldown = True
        self._test_transition_hlpr(
            event.UPDATE,
            state.CalcAction,
            instance_manager.ERROR,
        )

    def test_transition_poll_error_instance(self):
        self._test_transition_hlpr(
            event.POLL,
            state.CalcAction,
            instance_manager.ERROR,
        )


class TestAliveState(BaseTestStateCase):
    state_cls = state.Alive

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.instance.update_state.assert_called_once_with(self.ctx)

    def test_transition_instance_down(self):
        for evt in [event.POLL, event.READ, event.UPDATE, event.CREATE]:
            self._test_transition_hlpr(evt, state.CreateInstance, instance_manager.DOWN)

    def test_transition_poll_instance_configured(self):
        self._test_transition_hlpr(
            event.POLL,
            state.CalcAction,
            instance_manager.CONFIGURED
        )

    def test_transition_read_instance_configured(self):
        self._test_transition_hlpr(
            event.READ,
            state.ReadStats,
            instance_manager.CONFIGURED
        )

    def test_transition_up_to_configured(self):
        self._test_transition_hlpr(
            event.CREATE,
            state.ConfigureInstance,
            instance_manager.UP
        )

    def test_transition_configured_instance_configured(self):
        self._test_transition_hlpr(
            event.CREATE,
            state.ConfigureInstance,
            instance_manager.CONFIGURED
        )


class TestCreateInstanceState(BaseTestStateCase):
    state_cls = state.CreateInstance

    def test_execute(self):
        self.instance.attempts = 0
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.instance.boot.assert_called_once_with(self.ctx, 'GLANCE-IMAGE-123')

    def test_execute_too_many_attempts(self):
        self.instance.attempts = self.params.reboot_error_threshold
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.assertEqual([], self.instance.boot.mock_calls)
        self.instance.set_error.assert_called_once_with(self.ctx)

    def test_transition_instance_down(self):
        self._test_transition_hlpr(
            event.READ,
            state.CheckBoot,
            instance_manager.BOOTING
        )

    def test_transition_instance_up(self):
        self._test_transition_hlpr(
            event.READ,
            state.CheckBoot,
            instance_state=state.instance_manager.BOOTING
        )

    def test_transition_instance_missing(self):
        self._test_transition_hlpr(
            event.READ,
            state.CreateInstance,
            instance_state=state.instance_manager.DOWN
        )

    def test_transition_instance_error(self):
        self._test_transition_hlpr(event.READ, state.CalcAction,
                                   instance_state=state.instance_manager.ERROR)


class TestRebuildInstanceState(BaseTestStateCase):
    state_cls = state.RebuildInstance

    def test_execute(self):
        self.assertEqual(
            self.state.execute('ignored', self.ctx),
            event.CREATE,
        )
        self.instance.stop.assert_called_once_with(self.ctx)

    def test_execute_gone(self):
        self.instance.state = instance_manager.GONE
        self.assertEqual(
            self.state.execute('ignored', self.ctx),
            event.DELETE,
        )
        self.instance.stop.assert_called_once_with(self.ctx)


class TestClearErrorState(BaseTestStateCase):
    state_cls = state.ClearError

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough',
        )
        self.instance.clear_error.assert_called_once_with(self.ctx)

    def test_execute_after_error(self):
        self.instance.state = instance_manager.ERROR
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough',
        )
        self.instance.clear_error.assert_called_once_with(self.ctx)

    def test_transition_default(self):
        st = self.state_cls(self.params)
        self.assertIsInstance(
            st.transition('passthrough', self.ctx),
            state.CalcAction,
        )

    def test_transition_override(self):
        st = self.state_cls(self.params, state.Alive(self.params))
        self.assertIsInstance(
            st.transition('passthrough', self.ctx),
            state.Alive,
        )


class TestCheckBootState(BaseTestStateCase):
    state_cls = state.CheckBoot

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.instance.check_boot.assert_called_once_with(self.ctx)
        assert list(self.params.queue) == ['passthrough']

    def test_transition_instance_configure(self):
        self._test_transition_hlpr(
            event.UPDATE,
            state.ConfigureInstance,
            instance_manager.UP
        )

    def test_transition_instance_booting(self):
        self._test_transition_hlpr(
            event.UPDATE,
            state.CalcAction,
            instance_manager.BOOTING
        )


class TestStopInstanceState(BaseTestStateCase):
    state_cls = state.StopInstance

    def test_execute(self):
        self.assertEqual(
            self.state.execute('passthrough', self.ctx),
            'passthrough'
        )
        self.instance.stop.assert_called_once_with(self.ctx)

    def test_transition_instance_still_up(self):
        self._test_transition_hlpr(event.DELETE, state.StopInstance)

    def test_transition_delete_instance_down(self):
        self._test_transition_hlpr(event.DELETE,
                                   state.Exit,
                                   instance_manager.DOWN)

    def test_transition_restart_instance_down(self):
        self._test_transition_hlpr(event.READ,
                                   state.CreateInstance,
                                   instance_manager.DOWN)


class TestReplugState(BaseTestStateCase):
    state_cls = state.ReplugInstance

    def test_execute(self):
        self.assertEqual(
            self.state.execute('update', self.ctx),
            'update'
        )
        self.instance.replug.assert_called_once_with(self.ctx)

    def test_transition_hotplug_succeeded(self):
        self._test_transition_hlpr(
            event.UPDATE,
            state.ConfigureInstance,
            instance_manager.REPLUG
        )

    def test_transition_hotplug_failed(self):
        self._test_transition_hlpr(
            event.UPDATE,
            state.StopInstance,
            instance_manager.RESTART
        )


class TestExitState(TestBaseState):
    state_cls = state.Exit


class TestConfigureInstanceState(BaseTestStateCase):
    state_cls = state.ConfigureInstance

    def test_execute_read_configure_success(self):
        self.instance.state = instance_manager.CONFIGURED
        self.assertEqual(self.state.execute(event.READ, self.ctx),
                         event.READ)
        self.instance.configure.assert_called_once_with(self.ctx)

    def test_execute_update_configure_success(self):
        self.instance.state = instance_manager.CONFIGURED
        self.assertEqual(self.state.execute(event.UPDATE, self.ctx),
                         event.POLL)
        self.instance.configure.assert_called_once_with(self.ctx)

    def test_execute_configure_failure(self):
        self.assertEqual(
            self.state.execute(event.CREATE, self.ctx),
            event.CREATE
        )
        self.instance.configure.assert_called_once_with(self.ctx)

    def test_transition_not_configured_down(self):
        self._test_transition_hlpr(event.READ,
                                   state.StopInstance,
                                   instance_manager.DOWN)

    def test_transition_not_configured_restart(self):
        self._test_transition_hlpr(event.READ,
                                   state.StopInstance,
                                   instance_manager.RESTART)

    def test_transition_not_configured_up(self):
        self._test_transition_hlpr(event.READ,
                                   state.PushUpdate,
                                   instance_manager.UP)

    def test_transition_read_configured(self):
        self._test_transition_hlpr(
            event.READ,
            state.ReadStats,
            instance_manager.CONFIGURED
        )

    def test_transition_other_configured(self):
        self._test_transition_hlpr(
            event.POLL,
            state.CalcAction,
            instance_manager.CONFIGURED
        )


class TestReadStatsState(BaseTestStateCase):
    state_cls = state.ReadStats

    def test_execute(self):
        self.instance.read_stats.return_value = 'foo'

        self.assertEqual(
            self.state.execute(event.READ, self.ctx),
            event.POLL
        )
        self.instance.read_stats.assert_called_once_with()
        self.params.bandwidth_callback.assert_called_once_with('foo')

    def test_transition(self):
        self._test_transition_hlpr(event.POLL, state.CalcAction)


class TestAutomaton(unittest.TestCase):
    def setUp(self):
        super(TestAutomaton, self).setUp()

        self.ctx = mock.Mock()  # worker context

        self.instance_mgr_cls = \
            mock.patch('akanda.rug.instance_manager.InstanceManager').start()
        self.addCleanup(mock.patch.stopall)

        self.delete_callback = mock.Mock()
        self.bandwidth_callback = mock.Mock()

        self.sm = state.Automaton(
            router_id='9306bbd8-f3cc-11e2-bd68-080027e60b25',
            tenant_id='tenant-id',
            delete_callback=self.delete_callback,
            bandwidth_callback=self.bandwidth_callback,
            worker_context=self.ctx,
            queue_warning_threshold=3,
            reboot_error_threshold=5,
        )

    def test_send_message(self):
        message = mock.Mock()
        message.crud = 'update'
        with mock.patch.object(self.sm, 'log') as logger:
            self.sm.send_message(message)
            self.assertEqual(len(self.sm._queue), 1)
            logger.debug.assert_called_with(
                'incoming message brings queue length to %s',
                1,
            )

    def test_send_message_over_threshold(self):
        message = mock.Mock()
        message.crud = 'update'
        for i in range(3):
            self.sm.send_message(message)
        with mock.patch.object(self.sm, 'log') as logger:
            self.sm.send_message(message)
            logger.warning.assert_called_with(
                'incoming message brings queue length to %s',
                4,
            )

    def test_send_message_deleting(self):
        message = mock.Mock()
        message.crud = 'update'
        self.sm.deleted = True
        self.sm.send_message(message)
        self.assertEqual(len(self.sm._queue), 0)
        self.assertFalse(self.sm.has_more_work())

    def test_send_message_in_error(self):
        instance = self.instance_mgr_cls.return_value
        instance.state = state.instance_manager.ERROR
        message = mock.Mock()
        message.crud = 'poll'
        self.sm.send_message(message)
        self.assertEqual(len(self.sm._queue), 0)
        self.assertFalse(self.sm.has_more_work())

        # Non-POLL events should *not* be ignored for routers in ERROR state
        message.crud = 'create'
        with mock.patch.object(self.sm, 'log') as logger:
            self.sm.send_message(message)
            self.assertEqual(len(self.sm._queue), 1)
            logger.debug.assert_called_with(
                'incoming message brings queue length to %s',
                1,
            )

    def test_send_rebuild_message_with_custom_image(self):
        instance = self.instance_mgr_cls.return_value
        instance.state = state.instance_manager.DOWN
        with mock.patch.object(instance_manager.cfg, 'CONF') as conf:
            conf.router_image_uuid = 'DEFAULT'
            self.sm.state.params.router_image_uuid = conf.router_image_uuid

            message = mock.Mock()
            message.crud = 'rebuild'
            message.body = {'router_image_uuid': 'ABC123'}
            self.assertEqual(self.sm.router_image_uuid, conf.router_image_uuid)
            self.sm.send_message(message)
            self.assertEqual(self.sm.router_image_uuid, 'ABC123')

            message = mock.Mock()
            message.crud = 'rebuild'
            message.body = {}
            self.sm.send_message(message)
            self.assertEqual(self.sm.router_image_uuid, 'DEFAULT')

    def test_has_more_work(self):
        with mock.patch.object(self.sm, '_queue') as queue:  # noqa
            self.assertTrue(self.sm.has_more_work())

    def test_has_more_work_deleting(self):
        self.sm.deleted = True
        with mock.patch.object(self.sm, '_queue') as queue:  # noqa
            self.assertFalse(self.sm.has_more_work())

    def test_update_no_work(self):
        with mock.patch.object(self.sm, 'state') as state:
            self.sm.update(self.ctx)
            self.assertFalse(state.called)

    def test_update_exit(self):
        message = mock.Mock()
        message.crud = event.UPDATE
        self.sm.send_message(message)
        self.sm.state = state.Exit(mock.Mock())
        self.sm.update(self.ctx)
        self.delete_callback.called_once_with()

    def test_update_exception_during_excute(self):
        message = mock.Mock()
        message.crud = 'fake'
        self.sm.send_message(message)

        fake_state = mock.Mock()
        fake_state.execute.side_effect = Exception
        fake_state.transition.return_value = state.Exit(mock.Mock())
        self.sm.action = 'fake'
        self.sm.state = fake_state

        with mock.patch.object(self.sm, 'log') as log:
            self.sm.update(self.ctx)

            log.exception.assert_called_once_with(mock.ANY, fake_state, 'fake')

            fake_state.assert_has_calls(
                [
                    mock.call.execute('fake', self.ctx),
                    mock.call.transition('fake', self.ctx)
                ]
            )

    def test_update_calc_action_args(self):
        message = mock.Mock()
        message.crud = event.UPDATE
        self.sm.send_message(message)

        with mock.patch.object(self.sm.state, 'execute',
                               self.ctx) as execute:
            with mock.patch.object(self.sm.state, 'transition',
                                   self.ctx) as transition:
                transition.return_value = state.Exit(mock.Mock())
                self.sm.update(self.ctx)

                execute.called_once_with(
                    event.POLL,
                    self.instance_mgr_cls.return_value,
                    self.ctx,
                    self.sm._queue
                )
                self.delete_callback.called_once_with()

    def test_update_read_stats_args(self):
        message = mock.Mock()
        message.crud = event.READ
        self.sm.send_message(message)

        self.sm.state = state.ReadStats(mock.Mock())
        with mock.patch.object(self.sm.state, 'execute', self.ctx) as execute:
            execute.return_value = state.Exit(mock.Mock())
            self.sm.update(self.ctx)

            execute.called_once_with(
                event.POLL,
                self.instance_mgr_cls.return_value,
                self.ctx,
                self.bandwidth_callback
            )

    def test_has_error(self):
        with mock.patch.object(self.sm, 'instance') as instance:
            instance.state = instance_manager.ERROR
            self.assertTrue(self.sm.has_error())

    def test_has_no_error(self):
        with mock.patch.object(self.sm, 'instance') as instance:
            instance.state = instance_manager.UP
            self.assertFalse(self.sm.has_error())
