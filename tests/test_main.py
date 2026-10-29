import base64
import io
import sys
import types
import unittest
import wave
from unittest.mock import patch


class Plain:
    def __init__(self, text):
        self.text = text


class Record:
    def __init__(self, file):
        self.file = file

    @staticmethod
    def fromBase64(data):
        return Record(f"base64://{data}")


class MessageChain:
    def __init__(self, chain):
        self.chain = chain


class At:
    pass


class Reply:
    pass


class Image:
    pass


class Star:
    def __init__(self, context):
        self.context = context


def identity_decorator(*args, **kwargs):
    return lambda target: target


def install_module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


install_module("astrbot")
api_module = install_module("astrbot.api", AstrBotConfig=dict)
api_module.logger = types.SimpleNamespace(warning=lambda *args: None)
install_module(
    "astrbot.api.event",
    AstrMessageEvent=object,
    MessageChain=MessageChain,
    filter=types.SimpleNamespace(
        after_message_sent=identity_decorator,
        on_llm_response=identity_decorator,
    ),
)
install_module(
    "astrbot.api.star",
    Context=object,
    Star=Star,
    register=identity_decorator,
)
components_module = install_module(
    "astrbot.api.message_components",
    Plain=Plain,
    Record=Record,
    Image=Image,
    At=At,
    Reply=Reply,
)
api_module.message_components = components_module
install_module("fishaudio", AsyncFishAudio=object)
install_module("httpx", AsyncClient=object)

import main


class FakeContext:
    def __init__(self, translated_text="[happy] こんにちは", error=None):
        self.translated_text = translated_text
        self.error = error
        self.prompts = []
        self.provider_ids = []

    async def get_current_chat_provider_id(self, umo):
        self.provider_ids.append(umo)
        return "test-provider"

    async def llm_generate(self, chat_provider_id, prompt):
        if self.error is not None:
            raise self.error
        self.prompts.append((chat_provider_id, prompt))
        return types.SimpleNamespace(completion_text=self.translated_text)


class FakeTTS:
    def __init__(self, audio=b"RIFF-test-audio", error=None):
        self.audio = audio
        self.error = error
        self.calls = []

    async def convert(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.audio


class FakeFishClient:
    def __init__(self, audio=b"RIFF-test-audio", error=None):
        self.tts = FakeTTS(audio=audio, error=error)
        self.closed = False

    async def close(self):
        self.closed = True


class FakeEvent:
    def __init__(self, chain, platform="aiocqhttp"):
        self._result = types.SimpleNamespace(chain=chain)
        self._platform = platform
        self.unified_msg_origin = f"{platform}:group:123"
        self.sent_chains = []
        self.extras = {}

    def get_platform_name(self):
        return self._platform

    def get_result(self):
        return self._result

    async def send(self, chain):
        self.sent_chains.append(chain)

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value


class PluginTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = FakeContext()
        self.config = {
            "enabled": True,
            "probability": 1.0,
            "max_text_length": 40,
            "target_language": "日语",
            "fish_api_key": "secret-key",
            "fish_reference_id": "voice-id",
            "fish_proxy": "",
        }
        self.plugin = main.FishTtsTranslationPlugin(self.context, self.config)
        self.fish = FakeFishClient()
        self.plugin._fish_client = self.fish

    async def test_sends_voice_after_original_without_adding_text(self):
        original_chain = [Plain("今天真开心")]
        event = FakeEvent(original_chain)

        with patch("main.random.random", return_value=0.5):
            await self.plugin.after_message_sent(event)

        self.assertEqual(len(event.get_result().chain), 1)
        self.assertEqual(event.get_result().chain[0].text, "今天真开心")
        self.assertEqual(len(event.sent_chains), 1)
        self.assertEqual(len(event.sent_chains[0].chain), 1)
        record = event.sent_chains[0].chain[0]
        self.assertIsInstance(record, Record)
        encoded = record.file.removeprefix("base64://")
        self.assertEqual(base64.b64decode(encoded), b"RIFF-test-audio")

        call = self.fish.tts.calls[0]
        self.assertEqual(call["text"], "[happy] こんにちは")
        self.assertEqual(call["reference_id"], "voice-id")
        self.assertEqual(call["model"], "s2.1-pro-free")
        self.assertEqual(call["format"], "wav")
        self.assertEqual(call["latency"], "normal")
        provider_id, prompt = self.context.prompts[0]
        self.assertEqual(provider_id, "test-provider")
        self.assertIn("今天真开心", prompt)
        self.assertIn("日语", prompt)
        self.assertIn("方括号", prompt)

    async def test_multiple_text_segments_use_the_complete_sent_reply(self):
        event = FakeEvent([Reply(), At(), Plain("第一段。"), Plain("第二段。")])

        await self.plugin.after_message_sent(event)

        self.assertEqual(len(event.sent_chains), 1)
        prompt = self.context.prompts[0][1]
        self.assertIn("第一段。第二段。", prompt)
        self.assertEqual(len(event.get_result().chain), 4)

    async def test_full_llm_response_is_used_when_only_last_segment_remains(self):
        event = FakeEvent([Plain("最后一句。")])
        response = types.SimpleNamespace(completion_text="第一句。第二句。最后一句。")

        await self.plugin.on_llm_response(event, response)
        await self.plugin.after_message_sent(event)

        prompt = self.context.prompts[0][1]
        self.assertIn("第一句。第二句。最后一句。", prompt)
        self.assertEqual(len(event.sent_chains), 1)

    async def test_probability_zero_skips_all_external_calls(self):
        self.config["probability"] = 0.0
        event = FakeEvent([Plain("你好")])

        await self.plugin.after_message_sent(event)

        self.assertEqual(self.context.prompts, [])
        self.assertEqual(self.fish.tts.calls, [])
        self.assertEqual(len(event.get_result().chain), 1)

    async def test_over_length_text_is_not_processed(self):
        self.config["max_text_length"] = 3
        event = FakeEvent([Plain("四字文本")])

        await self.plugin.after_message_sent(event)

        self.assertEqual(self.context.prompts, [])
        self.assertEqual(self.fish.tts.calls, [])

    async def test_non_plain_and_non_qq_messages_are_not_processed(self):
        mixed_event = FakeEvent([Plain("你好"), Image()])
        other_platform_event = FakeEvent([Plain("你好")], platform="telegram")

        await self.plugin.after_message_sent(mixed_event)
        await self.plugin.after_message_sent(other_platform_event)

        self.assertEqual(self.context.prompts, [])
        self.assertEqual(self.fish.tts.calls, [])

    async def test_missing_voice_id_skips_translation(self):
        self.config["fish_reference_id"] = ""
        event = FakeEvent([Plain("你好")])

        with patch("main.random.random", return_value=0.0):
            await self.plugin.after_message_sent(event)

        self.assertEqual(self.context.prompts, [])
        self.assertEqual(self.fish.tts.calls, [])

    async def test_translation_failure_preserves_original_chain(self):
        self.context.error = RuntimeError("translation unavailable")
        event = FakeEvent([Plain("你好")])

        with patch("main.random.random", return_value=0.0):
            await self.plugin.after_message_sent(event)

        self.assertEqual(len(event.get_result().chain), 1)
        self.assertEqual(self.fish.tts.calls, [])

    async def test_empty_translation_does_not_call_tts(self):
        self.context.translated_text = "  "
        event = FakeEvent([Plain("你好")])

        with patch("main.random.random", return_value=0.0):
            await self.plugin.after_message_sent(event)

        self.assertEqual(len(event.get_result().chain), 1)
        self.assertEqual(self.fish.tts.calls, [])

    async def test_tts_failure_preserves_original_chain(self):
        self.fish = FakeFishClient(error=RuntimeError("tts unavailable"))
        self.plugin._fish_client = self.fish
        event = FakeEvent([Plain("你好")])

        with patch("main.random.random", return_value=0.0):
            await self.plugin.after_message_sent(event)

        self.assertEqual(len(event.get_result().chain), 1)
        self.assertEqual(len(self.fish.tts.calls), 1)

    async def test_disabled_plugin_does_nothing(self):
        self.config["enabled"] = False
        event = FakeEvent([Plain("你好")])

        await self.plugin.after_message_sent(event)

        self.assertEqual(self.context.prompts, [])
        self.assertEqual(self.fish.tts.calls, [])

    def test_adds_800ms_trailing_silence_without_changing_wav_format(self):
        source = io.BytesIO()
        with wave.open(source, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\x01\x00" * 80)

        padded = self.plugin._add_trailing_silence(source.getvalue())

        with wave.open(io.BytesIO(padded), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 8000)
            self.assertEqual(wav.getnframes(), 80 + 6400)
            frames = wav.readframes(wav.getnframes())
        self.assertTrue(frames.endswith(b"\x00" * (6400 * 2)))

    def test_explicit_proxy_is_passed_only_to_fish_client(self):
        self.plugin._fish_client = None

        with (
            patch("main.httpx.AsyncClient") as http_client,
            patch("main.AsyncFishAudio") as fish_client,
        ):
            self.plugin._get_fish_client("secret-key", "http://127.0.0.1:7890")

        http_client.assert_called_once_with(
            base_url="https://api.fish.audio",
            proxy="http://127.0.0.1:7890",
            timeout=main.FISH_TIMEOUT_SECONDS,
        )
        fish_client.assert_called_once_with(
            api_key="secret-key",
            timeout=main.FISH_TIMEOUT_SECONDS,
            httpx_client=http_client.return_value,
        )

    async def test_terminate_closes_fish_client(self):
        await self.plugin.terminate()

        self.assertTrue(self.fish.closed)
        self.assertIsNone(self.plugin._fish_client)


if __name__ == "__main__":
    unittest.main()
