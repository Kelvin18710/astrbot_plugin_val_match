import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import ImageDraw

from render import (
    RenderBracketMatch,
    RenderBracketRound,
    RenderBracketSection,
    RenderTournamentProgress,
    render_tournament_progress_image,
)


class CompleteBracketTests(unittest.TestCase):
    def test_all_eight_sections_are_drawn(self):
        sections = [
            RenderBracketSection(
                f"Section {i}",
                [
                    RenderBracketRound(
                        "Opening",
                        [RenderBracketMatch(f"Team{i}", "Opponent", "-", "-")],
                    )
                ],
            )
            for i in range(8)
        ]
        data = RenderTournamentProgress(
            event_name="Champions",
            stage_name="Groups",
            kind="bracket",
            groups=[],
            brackets=sections,
        )
        texts = []
        original = ImageDraw.ImageDraw.text

        def draw(self, xy, text, *args, **kwargs):
            texts.append(str(text))
            return original(self, xy, text, *args, **kwargs)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(ImageDraw.ImageDraw, "text", draw),
        ):
            render_tournament_progress_image(data, Path(tmp) / "bracket.png")
        for i in range(8):
            self.assertIn(f"Team{i}", texts)
