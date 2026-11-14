"""Exercise reply pacing and optional-request cancellation without platform I/O."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from weakref import WeakValueDictionary

import asyncio

from astrbot.api.event import MessageEventResult, ResultContentType
from astrbot.api.message_components import At, Image, Plain, Reply
from astrbot.core.astr_agent_run_util import _should_stop_agent
from astrbot.core.pipeline.respond import stage as respond
from data.plugins.astrbot_plugin_qqbot_features import reply_timing as timing
from data.plugins.astrbot_plugin_topic_concentration.main import TopicConcentrationPlugin


class Event:
    """Keep the public event and result surface, replacing only platform delivery."""

    def __init__(self, session="isolated", chain=None):
        self.unified_msg_origin = session
        self.message_obj = SimpleNamespace(message_id="source-1")
        self.extras = {timing.STARTED_AT_EXTRA: 100.0}
        self.result = MessageEventResult(chain=chain or [Plain("中" * 30), Plain("后续消息")], result_content_type=ResultContentType.LLM_RESULT)
        self.stopped = False
        self.sent = []
        self.failure = False

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_result(self):
        return self.result

    def clear_result(self):
        self.result = None

    def get_platform_name(self):
        return "aiocqhttp"

    def is_private_chat(self):
        return False

    def is_stopped(self):
        return self.stopped

    def stop_event(self):
        self.stopped = True

    def get_self_id(self):
        return "1443944862"

    def get_sender_id(self):
        return "123456789"

    def get_sender_name(self):
        return "isolated-user"

    def _outline_chain(self, chain):
        return "isolated"

    async def send(self, chain):
        if self.failure:
            raise ConnectionError("isolated unknown delivery")
        self.sent.append(chain.chain)


class ReplyTimingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock, self.waits = 101.0, []
        self.config = {"platform_settings": {"reply_prefix": "", "reply_with_mention": False,
            "reply_with_quote": False, "forward_threshold": 1500, "segmented_reply": {
                "enable": True, "interval_method": "random", "interval": "3.6,3.6",
                "words_count_threshold": 150, "regex": r".*?[。？！~…]+|.+$", "content_cleanup_rule": ""}},
            "provider_tts_settings": {"enable": False}}
        self.context = SimpleNamespace(get_config=lambda umo: self.config)
        self.time_patch = patch.object(timing, "time", SimpleNamespace(monotonic=lambda: self.clock))
        self.sleep_patch = patch.object(timing, "asyncio", SimpleNamespace(sleep=self.sleep))
        self.time_patch.start()
        self.sleep_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.addCleanup(self.sleep_patch.stop)

    async def sleep(self, delay):
        self.waits.append(delay)
        self.clock += delay

    async def test_first_budget_subtracts_work_but_second_wait_stays_full(self):
        event = Event()
        await timing.deliver_segmented_result(event, self.context)
        self.assertAlmostEqual(self.waits[0], 2.6)
        self.assertAlmostEqual(self.waits[1], 3.6)
        self.assertEqual(len(event.sent), 2)
        self.assertEqual(event.result.chain, [])
        timing.restore_delivered_result(event)
        self.assertEqual(len(event.result.chain), 2)

    async def test_slow_first_and_research_followup(self):
        self.clock = 105
        event = Event(chain=[Plain("首条结论")])
        await timing.deliver_segmented_result(event, self.context)
        self.assertEqual(self.waits, [])
        timing.restore_delivered_result(event)
        self.clock = 150
        event.result = MessageEventResult(chain=[Plain("查证后的补充")], result_content_type=ResultContentType.LLM_RESULT)
        await timing.deliver_segmented_result(event, self.context)
        self.assertEqual(self.waits, [3.6])

    async def test_native_after_send_hook_runs_once_without_resending(self):
        event = Event()
        await timing.deliver_segmented_result(event, self.context)
        async def after_sent(current, kind):
            timing.restore_delivered_result(current)
            self.assertEqual(len(current.get_result().chain), 2)
            return False
        callback = AsyncMock(side_effect=after_sent)
        with patch.object(respond, "call_event_hook", callback):
            await respond.RespondStage().process(event)
        callback.assert_awaited_once()
        self.assertEqual(len(event.sent), 2)
        self.assertIsNone(event.result)

    async def test_header_and_image_order_survives(self):
        event = Event(chain=[Reply(id="quoted"), At(qq="123456789"), Plain("首条"), Image(file="https://example.invalid/image"), Plain("后续")])
        await timing.deliver_segmented_result(event, self.context)
        self.assertEqual([type(part) for part in event.sent[0]], [Reply, At, Plain])
        self.assertEqual([type(part) for part in event.sent[1]], [Image])
        self.assertEqual([type(part) for part in event.sent[2]], [Plain])

    async def test_unknown_failure_never_falls_through_to_native_resend(self):
        event = Event(chain=[Plain("隔离正文")])
        event.failure = True
        await timing.deliver_segmented_result(event, self.context)
        self.assertEqual(event.result.chain, [])
        self.assertTrue(event.get_extra(timing.FIRST_DELIVERY_EXTRA))
        timing.restore_delivered_result(event)
        self.assertEqual(event.result.chain, [])

    async def test_general_result_marks_first_before_later_model_output(self):
        event = Event()
        event.result.set_result_content_type(ResultContentType.GENERAL_RESULT)
        await timing.deliver_segmented_result(event, self.context)
        self.assertEqual(event.sent, [])
        timing.restore_delivered_result(event)
        self.assertTrue(event.get_extra(timing.FIRST_DELIVERY_EXTRA))

    async def test_cancellation_keeps_native_chain_empty(self):
        event = Event()
        async def cancel(delay):
            raise asyncio.CancelledError
        with patch.object(timing, "asyncio", SimpleNamespace(sleep=cancel)):
            with self.assertRaises(asyncio.CancelledError):
                await timing.deliver_segmented_result(event, self.context)
        self.assertEqual(event.result.chain, [])


class RequestPriorityTests(IsolatedAsyncioTestCase):
    async def test_direct_request_stops_only_old_optional_work_in_same_session(self):
        plugin = TopicConcentrationPlugin.__new__(TopicConcentrationPlugin)
        plugin._reply_events = WeakValueDictionary()
        old, other, direct = Event(), Event("other"), Event()
        self.assertTrue(plugin._track_reply_request(old, low_priority=True))
        self.assertTrue(plugin._track_reply_request(other, low_priority=True))
        self.assertTrue(plugin._track_reply_request(direct, low_priority=False))
        self.assertTrue(old.is_stopped())
        self.assertTrue(_should_stop_agent(old))
        self.assertFalse(other.is_stopped())
        self.assertFalse(direct.is_stopped())
        new_optional = Event()
        self.assertFalse(plugin._track_reply_request(new_optional, low_priority=True))
        self.assertTrue(new_optional.is_stopped())
        another_direct = Event()
        self.assertTrue(plugin._track_reply_request(another_direct, low_priority=False))
        self.assertFalse(direct.is_stopped())
