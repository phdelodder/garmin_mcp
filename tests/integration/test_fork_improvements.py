"""
Integration tests for phdelodder/garmin_mcp fork improvements.

Covers all 7 changes introduced in commits 625f041..86736f1:
  1. get_training_load_trend: device-map iteration (ATL/CTL extraction)
  2. get_training_load_trend: trainingStatusDTO path fix
  3. get_stats: body_battery_realtime_depleted rename
  4. get_vo2max_trend: cycling_vo2_max field
  5. get_activity_splits: cadence divergence warning in docstring
  6. get_morning_wellness: new tool
  7. get_activity_rpe: new tool
"""

import json
import pytest
from unittest.mock import Mock, patch
from mcp.server.fastmcp import FastMCP

from garmin_mcp import training, health_wellness, activity_management


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_app(module, mock_client):
    module.configure(mock_client)
    app = FastMCP("test")
    module.register_tools(app)
    return app


def _text(result) -> str:
    contents, _ = result
    return contents[0].text


# ── fixtures ───────────────────────────────────────────────────────────────────

DEVICE_ID = "3765432100"

MOCK_TRAINING_STATUS_WITH_DEVICE_MAP = {
    "mostRecentTrainingStatus": {
        "latestTrainingStatusData": {
            DEVICE_ID: {
                "acuteTrainingLoadDTO": {
                    "dailyTrainingLoadAcute": 55.3,
                    "dailyTrainingLoadChronic": 48.7,
                    "dailyAcuteChronicWorkloadRatio": 1.135,
                    "acwrStatus": "OPTIMAL",
                },
                "trainingStatusDTO": {
                    "trainingStatusCyclingFeedbackPhrase": "PRODUCTIVE",
                },
            }
        }
    },
    "mostRecentVO2Max": {
        "generic": {"vo2MaxValue": 54.0},
        "cycling": {"vo2MaxPreciseValue": 52.9, "vo2MaxValue": 52.0},
    },
}

MOCK_TRAINING_STATUS_WITH_NULLS = {
    "mostRecentTrainingStatus": None,
    "mostRecentVO2Max": None,
    "mostRecentTrainingLoadBalance": None,
}


# ── 1 & 2: get_training_load_trend device-map + trainingStatusDTO path ─────────

class TestTrainingLoadTrendDeviceMap:
    @pytest.fixture(autouse=True)
    def setup(self, mock_garmin_client):
        mock_garmin_client.get_training_status = Mock(
            return_value=MOCK_TRAINING_STATUS_WITH_DEVICE_MAP
        )
        self.app = _make_app(training, mock_garmin_client)

    @pytest.mark.asyncio
    async def test_atl_extracted_from_device_map(self):
        result = await self.app.call_tool("get_training_load_trend", {"start_date": "2026-06-22", "end_date": "2026-06-22"})
        data = json.loads(_text(result))
        entry = data["trend"][0]
        assert entry["atl"] == 55.3

    @pytest.mark.asyncio
    async def test_ctl_extracted_from_device_map(self):
        result = await self.app.call_tool("get_training_load_trend", {"start_date": "2026-06-22", "end_date": "2026-06-22"})
        data = json.loads(_text(result))
        entry = data["trend"][0]
        assert entry["ctl"] == 48.7

    @pytest.mark.asyncio
    async def test_tsb_derived(self):
        result = await self.app.call_tool("get_training_load_trend", {"start_date": "2026-06-22", "end_date": "2026-06-22"})
        data = json.loads(_text(result))
        entry = data["trend"][0]
        assert entry["tsb"] == round(48.7 - 55.3, 1)

    @pytest.mark.asyncio
    async def test_acwr_extracted(self):
        result = await self.app.call_tool("get_training_load_trend", {"start_date": "2026-06-22", "end_date": "2026-06-22"})
        data = json.loads(_text(result))
        entry = data["trend"][0]
        assert entry["acwr"] == 1.14

    @pytest.mark.asyncio
    async def test_training_status_label_from_device_data(self):
        result = await self.app.call_tool("get_training_load_trend", {"start_date": "2026-06-22", "end_date": "2026-06-22"})
        data = json.loads(_text(result))
        entry = data["trend"][0]
        assert entry.get("training_status") == "PRODUCTIVE"

    @pytest.mark.asyncio
    async def test_null_status_does_not_crash(self, mock_garmin_client):
        mock_garmin_client.get_training_status = Mock(
            return_value=MOCK_TRAINING_STATUS_WITH_NULLS
        )
        self.app = _make_app(training, mock_garmin_client)
        result = await self.app.call_tool("get_training_load_trend", {"start_date": "2026-06-22", "end_date": "2026-06-22"})
        text = _text(result)
        assert "Error" not in text or "No" in text


# ── 3: body_battery_realtime_depleted rename ────────────────────────────────────

class TestBodyBatteryRename:
    @pytest.fixture(autouse=True)
    def setup(self, mock_garmin_client):
        mock_garmin_client.get_stats = Mock(return_value={
            "calendarDate": "2026-06-22",
            "bodyBatteryMostRecentValue": 61,
            "bodyBatteryChargedValue": 65,
            "bodyBatteryDrainedValue": 35,
        })
        self.app = _make_app(health_wellness, mock_garmin_client)

    @pytest.mark.asyncio
    async def test_new_field_name_present(self):
        result = await self.app.call_tool("get_stats", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert "body_battery_realtime_depleted" in data

    @pytest.mark.asyncio
    async def test_old_field_name_absent(self):
        result = await self.app.call_tool("get_stats", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert "body_battery_current" not in data

    @pytest.mark.asyncio
    async def test_value_preserved(self):
        result = await self.app.call_tool("get_stats", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert data["body_battery_realtime_depleted"] == 61


# ── 4: cycling_vo2_max in get_vo2max_trend ──────────────────────────────────────

class TestCyclingVo2Max:
    @pytest.fixture(autouse=True)
    def setup(self, mock_garmin_client):
        mock_garmin_client.get_training_status = Mock(
            return_value=MOCK_TRAINING_STATUS_WITH_DEVICE_MAP
        )
        self.app = _make_app(training, mock_garmin_client)

    @pytest.mark.asyncio
    async def test_cycling_vo2_max_present(self):
        result = await self.app.call_tool("get_vo2max_trend", {"start_date": "2026-06-14", "end_date": "2026-06-14"})
        data = json.loads(_text(result))
        assert data["trend"][0].get("cycling_vo2_max") == 52.9

    @pytest.mark.asyncio
    async def test_generic_vo2_max_still_present(self):
        result = await self.app.call_tool("get_vo2max_trend", {"start_date": "2026-06-14", "end_date": "2026-06-14"})
        data = json.loads(_text(result))
        assert data["trend"][0].get("vo2_max") == 54.0


# ── 5: cadence warning in get_activity_splits docstring ────────────────────────

class TestCadenceWarning:
    def test_docstring_contains_divergence_warning(self, mock_garmin_client):
        app = _make_app(activity_management, mock_garmin_client)
        tool = next(t for t in app._tool_manager.list_tools() if t.name == "get_activity_splits")
        assert "13 rpm" in (tool.description or "")


# ── 6: get_morning_wellness ─────────────────────────────────────────────────────

class TestMorningWellness:
    @pytest.fixture(autouse=True)
    def setup(self, mock_garmin_client):
        mock_garmin_client.get_user_summary = Mock(return_value={
            "bodyBatteryAtWakeTime": 87,
            "restingHeartRate": 43,
            "lastSevenDaysAvgRestingHeartRate": 45,
            "averageStressLevel": 12,
        })
        mock_garmin_client.get_sleep_data = Mock(return_value={
            "dailySleepDTO": {
                "sleepTimeSeconds": 28800,
                "sleepScores": {
                    "overall": {"value": 82, "qualifierKey": "GOOD"}
                },
            }
        })
        mock_garmin_client.get_hrv_data = Mock(return_value={
            "hrvSummary": {
                "lastNightAvg": 48.0,
                "weeklyAvg": 45.0,
                "status": "BALANCED",
            }
        })
        self.app = _make_app(health_wellness, mock_garmin_client)

    @pytest.mark.asyncio
    async def test_body_battery_at_wake_time(self):
        result = await self.app.call_tool("get_morning_wellness", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert data["body_battery_at_wake_time"] == 87

    @pytest.mark.asyncio
    async def test_rhr_present(self):
        result = await self.app.call_tool("get_morning_wellness", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert data["resting_heart_rate_bpm"] == 43

    @pytest.mark.asyncio
    async def test_sleep_hours_computed(self):
        result = await self.app.call_tool("get_morning_wellness", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert data["sleep_hours"] == 8.0

    @pytest.mark.asyncio
    async def test_hrv_present(self):
        result = await self.app.call_tool("get_morning_wellness", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert data["hrv_last_night_avg_ms"] == 48.0

    @pytest.mark.asyncio
    async def test_hrv_failure_does_not_crash(self, mock_garmin_client):
        mock_garmin_client.get_hrv_data = Mock(side_effect=Exception("HRV unavailable"))
        self.app = _make_app(health_wellness, mock_garmin_client)
        result = await self.app.call_tool("get_morning_wellness", {"date": "2026-06-22"})
        data = json.loads(_text(result))
        assert "body_battery_at_wake_time" in data


# ── 7: get_activity_rpe ─────────────────────────────────────────────────────────

class TestActivityRpe:
    @pytest.fixture(autouse=True)
    def setup(self, mock_garmin_client):
        mock_garmin_client.connectapi = Mock(return_value=[
            {"activityId": 23403084294, "activityName": "Threshold TTE · 2×20", "startTimeLocal": "2026-06-28 06:27:01"},
        ])
        mock_garmin_client.get_activity = Mock(return_value={
            "summaryDTO": {"directWorkoutRpe": 60}
        })
        mock_garmin_client.garmin_connect_activities = "/proxy/activitylist-service/activities/search/activities"
        self.app = _make_app(activity_management, mock_garmin_client)

    @pytest.mark.asyncio
    async def test_rpe_borg_scale(self):
        result = await self.app.call_tool("get_activity_rpe", {"date": "2026-06-28"})
        data = json.loads(_text(result))
        assert data["rpe_borg_1_10"] == 6.0

    @pytest.mark.asyncio
    async def test_rpe_raw_value(self):
        result = await self.app.call_tool("get_activity_rpe", {"date": "2026-06-28"})
        data = json.loads(_text(result))
        assert data["rpe_raw_0_100"] == 60

    @pytest.mark.asyncio
    async def test_activity_id_present(self):
        result = await self.app.call_tool("get_activity_rpe", {"date": "2026-06-28"})
        data = json.loads(_text(result))
        assert data["activity_id"] == 23403084294

    @pytest.mark.asyncio
    async def test_name_hint_filters(self, mock_garmin_client):
        mock_garmin_client.connectapi = Mock(return_value=[
            {"activityId": 111, "activityName": "Morning Ride"},
            {"activityId": 222, "activityName": "Threshold TTE"},
        ])
        mock_garmin_client.get_activity = Mock(return_value={"summaryDTO": {"directWorkoutRpe": 60}})
        mock_garmin_client.garmin_connect_activities = "/proxy/activitylist-service/activities/search/activities"
        app = _make_app(activity_management, mock_garmin_client)
        result = await app.call_tool("get_activity_rpe", {"date": "2026-06-28", "name_hint": "threshold"})
        text = _text(result)
        data = json.loads(text)
        # When hint matches one, result is a single dict not a list
        if isinstance(data, list):
            assert all(d["activity_id"] == 222 for d in data)
        else:
            assert data["activity_id"] == 222
