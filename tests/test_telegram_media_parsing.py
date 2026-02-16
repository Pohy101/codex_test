from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.clients.telegram_client import extract_telegram_media_items, render_telegram_fallback_text


class TelegramMediaParsingTests(unittest.TestCase):
    def _base_message(self) -> SimpleNamespace:
        return SimpleNamespace(
            audio=None,
            voice=None,
            sticker=None,
            animation=None,
            video_note=None,
            photo=None,
            video=None,
            document=None,
            text=None,
            caption=None,
            entities=None,
            caption_entities=None,
            reactions=None,
            reaction=None,
        )

    def test_extract_audio(self) -> None:
        msg = self._base_message()
        msg.audio = SimpleNamespace(
            file_id="audio-id",
            file_unique_id="audio-uniq",
            file_name="song.mp3",
            mime_type="audio/mpeg",
            duration=7,
            file_size=111,
        )

        media_items = extract_telegram_media_items(msg)

        self.assertEqual(1, len(media_items))
        item = media_items[0]
        self.assertEqual("audio", item.kind)
        self.assertEqual("audio-id", item.platform_file_id)
        self.assertEqual("audio-uniq", item.platform_file_unique_id)
        self.assertEqual("audio/mpeg", item.mime_type)
        self.assertEqual(7, item.duration)

    def test_extract_voice(self) -> None:
        msg = self._base_message()
        msg.voice = SimpleNamespace(
            file_id="voice-id",
            file_unique_id="voice-uniq",
            mime_type="audio/ogg",
            duration=4,
            file_size=222,
        )

        item = extract_telegram_media_items(msg)[0]
        self.assertEqual("voice", item.kind)
        self.assertEqual("voice_voice-uniq.ogg", item.filename)

    def test_extract_sticker_with_restore_metadata(self) -> None:
        msg = self._base_message()
        msg.sticker = SimpleNamespace(
            file_id="sticker-id",
            file_unique_id="sticker-uniq",
            mime_type="application/x-tgsticker",
            file_size=333,
            emoji="🔥",
            set_name="setA",
            is_animated=True,
            is_video=False,
        )

        item = extract_telegram_media_items(msg)[0]
        self.assertEqual("sticker", item.kind)
        self.assertEqual("sticker-id", item.platform_file_id)
        self.assertEqual("🔥", item.emoji)
        self.assertTrue(item.is_animated)
        self.assertFalse(item.is_video)

    def test_extract_animation(self) -> None:
        msg = self._base_message()
        msg.animation = SimpleNamespace(
            file_id="anim-id",
            file_unique_id="anim-uniq",
            file_name="anim.gif",
            mime_type="image/gif",
            duration=2,
            file_size=444,
        )

        item = extract_telegram_media_items(msg)[0]
        self.assertEqual("animation", item.kind)
        self.assertEqual("image/gif", item.mime_type)

    def test_extract_video_note(self) -> None:
        msg = self._base_message()
        msg.video_note = SimpleNamespace(
            file_id="vn-id",
            file_unique_id="vn-uniq",
            duration=9,
            file_size=555,
        )

        item = extract_telegram_media_items(msg)[0]
        self.assertEqual("video_note", item.kind)
        self.assertEqual("video/mp4", item.mime_type)
        self.assertEqual("video_note_vn-uniq.mp4", item.filename)

    def test_extract_photo(self) -> None:
        msg = self._base_message()
        msg.photo = [
            SimpleNamespace(file_id="small", file_unique_id="small-u", file_size=10),
            SimpleNamespace(file_id="big", file_unique_id="big-u", file_size=20),
        ]

        item = extract_telegram_media_items(msg)[0]
        self.assertEqual("photo", item.kind)
        self.assertEqual("big", item.platform_file_id)
        self.assertEqual("photo_big-u.jpg", item.filename)

    def test_extract_video(self) -> None:
        msg = self._base_message()
        msg.video = SimpleNamespace(
            file_id="video-id",
            file_unique_id="video-uniq",
            file_name="movie.mp4",
            mime_type="video/mp4",
            duration=15,
            file_size=666,
        )

        item = extract_telegram_media_items(msg)[0]
        self.assertEqual("video", item.kind)
        self.assertEqual(15, item.duration)

    def test_extract_document(self) -> None:
        msg = self._base_message()
        msg.document = SimpleNamespace(
            file_id="doc-id",
            file_unique_id="doc-uniq",
            file_name="report.pdf",
            mime_type="application/pdf",
            file_size=777,
        )

        item = extract_telegram_media_items(msg)[0]
        self.assertEqual("document", item.kind)
        self.assertEqual("application/pdf", item.mime_type)

    def test_extract_custom_emoji_and_reaction_with_fallback_text(self) -> None:
        msg = self._base_message()
        msg.text = "wow 😎"
        msg.entities = [SimpleNamespace(type="custom_emoji", offset=4, length=1, custom_emoji_id="ce-1")]
        msg.reactions = [SimpleNamespace(emoji="❤️")]

        media_items = extract_telegram_media_items(msg)

        kinds = [item.kind for item in media_items]
        self.assertIn("custom_emoji", kinds)
        self.assertIn("reaction", kinds)
        fallback = render_telegram_fallback_text(media_items)
        self.assertIn("Custom emoji", fallback)
        self.assertIn("Reaction: ❤️", fallback)


if __name__ == "__main__":
    unittest.main()
