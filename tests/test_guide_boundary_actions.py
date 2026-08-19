from __future__ import annotations

from datetime import datetime, timedelta, timezone

from channelos.guide import GuideController, GuideProgram

UTC = timezone.utc


class FakeGuideService:
    def __init__(self) -> None:
        self.validated: GuideProgram | None = None

    def validate_program(self, program: GuideProgram):
        self.validated = program
        return object()


class FakeTelevision:
    def __init__(self) -> None:
        self.called_with: tuple[int, datetime, datetime] | None = None
        self.result = object()

    def watch_from_beginning(self, channel_number: int, program_started_at: datetime, *, now: datetime):
        self.called_with = (channel_number, program_started_at, now)
        return self.result


def test_watch_from_beginning_probes_one_microsecond_inside_selected_occurrence() -> None:
    start = datetime(2026, 8, 19, 17, 30, 39, 123456, tzinfo=UTC)
    end = start + timedelta(seconds=20.133)
    reference = end + timedelta(seconds=54.667)
    program = GuideProgram(
        schedule_id="occurrence",
        channel_number=7,
        asset_id="sha256:selected",
        display_label="selected-program",
        start_utc=start,
        end_utc=end,
        duration_seconds=20.133,
        programming_mode="sequential",
        explanation=(),
        is_current=False,
        is_past=True,
        is_future=False,
    )
    service = FakeGuideService()
    television = FakeTelevision()
    controller = GuideController(service, television)  # type: ignore[arg-type]

    result = controller.watch_from_beginning(program, at=reference)

    assert result is television.result
    assert service.validated is program
    assert television.called_with == (
        7,
        start + timedelta(microseconds=1),
        reference,
    )
