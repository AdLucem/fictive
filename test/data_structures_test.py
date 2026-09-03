import json
import tempfile
import unittest
from types import SimpleNamespace

from fictive.data_structures import History, Scene, Store

class HistoryTests(unittest.TestCase):
    def test_main_example_history_merges_consecutive_user_messages(self):
        """Tests History.read() merging behavior after History.add_role_content() appends messages."""
        hist = History(names={"user": "MyName", "assistant": "Character"})

        hist.add_role_content(role="system", content="This is a system prompt.")
        hist.add_role_content(
            role="user",
            content="I am making a request of this system",
        )
        hist.add_role_content(
            role="assistant",
            content="Hello, I am responding to your first request",
        )
        hist.add_role_content(
            role="user",
            content="Gee golly willikers, you sure are alive!",
        )
        hist.add_role_content(
            role="user",
            content="(INSTRUCTIONS: I am giving you some instructions here)",
        )
        hist.add_role_content(
            role="assistant",
            content="Hello, yeah I am sure alive!",
        )

        self.assertEqual(
            hist.read(merged=False),
            [
                {"role": "system", "content": "This is a system prompt."},
                {
                    "role": "user",
                    "content": "I am making a request of this system",
                },
                {
                    "role": "assistant",
                    "content": "Hello, I am responding to your first request",
                },
                {
                    "role": "user",
                    "content": "Gee golly willikers, you sure are alive!",
                },
                {
                    "role": "user",
                    "content": "(INSTRUCTIONS: I am giving you some instructions here)",
                },
                {
                    "role": "assistant",
                    "content": "Hello, yeah I am sure alive!",
                },
            ],
        )
        self.assertEqual(
            hist.read(),
            [
                {"role": "system", "content": "This is a system prompt."},
                {
                    "role": "user",
                    "content": "I am making a request of this system",
                },
                {
                    "role": "assistant",
                    "content": "Hello, I am responding to your first request",
                },
                {
                    "role": "user",
                    "content": (
                        "Gee golly willikers, you sure are alive!\n\n "
                        "(INSTRUCTIONS: I am giving you some instructions here)"
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Hello, yeah I am sure alive!",
                },
            ],
        )

    def test_add_accepts_single_message_and_sequence(self):
        """Tests History.add() accepting both one message dict and a sequence of message dicts."""
        hist = History()

        hist.add({"role": "system", "content": "setup"})
        hist.add(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ]
        )

        self.assertEqual(
            hist.read(merged=False),
            [
                {"role": "system", "content": "setup"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ],
        )

    def test_add_rejects_bad_message_shapes(self):
        """Tests History.add() validation for malformed message inputs."""
        hist = History()

        with self.assertRaisesRegex(Exception, "wrong format"):
            hist.add({"role": "user"})

        with self.assertRaisesRegex(Exception, "wrong format"):
            hist.add("not-a-message")

    def test_remove_without_filters_pops_last_message(self):
        """Tests History.remove() with no filters removing the last stored message."""
        hist = History(
            init_list=[
                {"role": "system", "content": "setup"},
                {"role": "user", "content": "request"},
            ]
        )

        removed = hist.remove()

        self.assertIsNone(removed)
        self.assertEqual(
            hist.read(merged=False),
            [{"role": "system", "content": "setup"}],
        )

    def test_remove_by_role_returns_tail_without_mutating_history(self):
        """Tests History.remove(role=...) returning the matching tail while leaving history unchanged."""
        hist = History(
            init_list=[
                {"role": "system", "content": "setup"},
                {"role": "user", "content": "request"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "follow-up"},
            ]
        )

        removed = hist.remove(role="assistant")

        self.assertEqual(
            removed,
            [
                {"role": "user", "content": "follow-up"},
                {"role": "assistant", "content": "reply"},
            ],
        )
        self.assertEqual(
            hist.read(merged=False),
            [
                {"role": "system", "content": "setup"},
                {"role": "user", "content": "request"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "follow-up"},
            ],
        )

    def test_set_values_appends_messages(self):
        """Tests History.set_values() appending new messages to existing history."""
        hist = History(
            init_list=[{"role": "system", "content": "existing"}]
        )

        hist.set_values(
            [
                {"role": "user", "content": "new request"},
                {"role": "assistant", "content": "new reply"},
            ]
        )

        self.assertEqual(
            hist.read(merged=False),
            [
                {"role": "system", "content": "existing"},
                {"role": "user", "content": "new request"},
                {"role": "assistant", "content": "new reply"},
            ],
        )

    def test_to_scene_uses_names_and_strips_instruction_blocks(self):
        """Tests History.to_scene() rendering names and removing instruction-only content."""
        hist = History(
            names={"user": "MyName", "assistant": "Character"},
            init_list=[
                {"role": "system", "content": "This is a system prompt."},
                {"role": "user", "content": "Scene setup from the user."},
                {
                    "role": "user",
                    "content": "Say hello. (INSTRUCTIONS: hidden note)",
                },
                {"role": "assistant", "content": "Hello there!"},
                {
                    "role": "user",
                    "content": "(INSTRUCTIONS: hidden note only)",
                },
            ],
        )

        self.assertEqual(
            hist.to_scene(),
            (
                "Scene setup from the user.\n"
                "\nMyName: Say hello.\n"
                "\nCharacter: Hello there!\n"
            ),
        )

    def test_save_writes_merged_history_as_json(self):
        """Tests History.save() serializing merged history to JSON."""
        hist = History(
            init_list=[
                {"role": "user", "content": "first"},
                {"role": "user", "content": "second"},
            ]
        )

        with tempfile.NamedTemporaryFile("r+", encoding="utf-8") as tmp:
            hist.save(tmp.name)
            tmp.seek(0)
            saved = json.load(tmp)

        self.assertEqual(
            saved,
            [{"role": "user", "content": "first\n\n second"}],
        )

    def test_get_name_and_repr_use_name_mapping(self):

        """Tests History.get_name() and History.__repr__() using configured role names."""
        hist = History(
            names={"user": "MyName"},
            init_list=[{"role": "user", "content": "hello"}],
        )

        self.assertEqual(hist.get_name("user"), "MyName")
        self.assertEqual(hist.get_name("assistant"), "assistant")
        self.assertIn("MyName", repr(hist))
        self.assertIn("hello", repr(hist))

    def test_read_returns_strings_only(self):

        """Messages in history may contain non-string values like lists or dicts (for example, for a function-calling model). However, `read` should always return all messages as strings. However, reading the history should NOT change the original format of messages within self._h."""

        hist = History()

        m1 = {"role": "user", "content": "Hello world"}
        m2 = {
            "role": "assistant", 
            "content": {
                "function": "test",
                "reason": "test reason"
            }}
        m2_str = {
            "role": "assistant", 
            "content": str({
                "function": "test",
                "reason": "test reason"
            })}

        hist.add(m1)
        hist.add(m2)

        self.assertEqual(hist.read(), [m1, m2_str])
        self.assertEqual(hist._h, [m1, m2])




class SceneTests(unittest.TestCase):
    def test_init_with_scene_and_show_formats_dialogue(self):
        """Tests Scene initialization from init_scene and Scene.show() dialogue formatting."""
        scene = Scene(
            names={"user": "MyName", "assistant": "Character"},
            init_scene=[
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Opening scene"},
                {"role": "assistant", "content": "Hello, I am an assistant."},
            ],
        )

        self.assertEqual(
            scene.show(),
            "Opening scene\n\nCharacter: Hello, I am an assistant.\n",
        )
        self.assertEqual(repr(scene), scene.show())

    def test_init_with_agent_uses_first_two_history_messages(self):
        """Tests Scene(agent=...) copying the opening scene from the agent history."""
        agent_history = History(
            init_list=[
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Opening scene"},
                {"role": "assistant", "content": "Should not be copied"},
            ]
        )
        agent = SimpleNamespace(history=agent_history)

        scene = Scene(agent=agent)

        self.assertEqual(
            scene.scene.read(merged=False),
            [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Opening scene"},
            ],
        )

    def test_add_skips_messages_with_excluded_words(self):
        """Tests Scene.add() ignoring messages whose content matches excluded instruction text."""
        scene = Scene(
            init_scene=[
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Opening scene"},
            ]
        )

        returned = scene.add(
            {"role": "user", "content": "(INSTRUCTIONS: hidden)"},
        )

        self.assertIs(returned, scene.scene)
        self.assertEqual(
            scene.scene.read(merged=False),
            [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Opening scene"},
            ],
        )

    def test_add_non_excluded_user_message_currently_raises_type_error(self):
        """Tests the current Scene.add() behavior for visible user content raising TypeError."""
        scene = Scene(
            init_scene=[
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Opening scene"},
            ]
        )

        with self.assertRaises(TypeError):
            scene.add({"role": "user", "content": "Visible line"})


class StoreTests(unittest.TestCase):
    def test_get_returns_none_for_missing_values(self):
        """Tests Store.get() returning None when a key has not been set."""
        store = Store()

        self.assertIsNone(store.get("missing"))

    def test_set_and_get_round_trip_values(self):
        """Tests Store.set() and Store.get() preserving assigned values."""
        store = Store()

        store.set("mood", "curious")
        store.set("turn", 3)

        self.assertEqual(store.get("mood"), "curious")
        self.assertEqual(store.get("turn"), 3)

    def test_repr_lists_stored_pairs(self):
        """Tests Store.__repr__() including the stored key/value pairs in its output."""
        store = Store()
        store.set("mood", "curious")

        rendered = repr(store)

        self.assertIn("STORE ++++", rendered)
        self.assertIn("mood = curious", rendered)


if __name__ == "__main__":
    unittest.main()
