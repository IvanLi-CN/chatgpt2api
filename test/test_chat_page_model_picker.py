from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_PAGE = ROOT / "web" / "src" / "app" / "chat" / "page.tsx"


class ChatPageModelPickerTests(unittest.TestCase):
    def source(self) -> str:
        return CHAT_PAGE.read_text(encoding="utf-8")

    def test_chat_page_loads_models_from_v1_models(self) -> None:
        source = self.source()

        self.assertIn("modelsEndpoint(", source)
        self.assertIn("loadModels", source)
        self.assertIn("/models", source)
        self.assertIn("setModelOptions", source)

    def test_chat_page_renders_model_select_items(self) -> None:
        source = self.source()

        self.assertIn("SelectContent", source)
        self.assertIn("SelectItem", source)
        self.assertIn("modelOptions.map", source)


if __name__ == "__main__":
    unittest.main()
