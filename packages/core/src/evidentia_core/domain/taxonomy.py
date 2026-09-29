"""Project activity taxonomies.

Each project gets a versioned list of activities. The same definitions drive:
  * the upload form (what the field team declares),
  * Cloudinary AI Vision tag definitions (yes/no questions, max 10 per request),
  * the VLM extraction prompt (allowed activity keys),
  * later: search filters, timelines and report sections.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_KEY = re.compile(r"^[a-z][a-z0-9_]{1,47}$")


class Activity(BaseModel):
    key: str = Field(description="machine key, snake_case")
    label: str
    description: str = Field(description="What is visibly true when this activity is depicted")
    question: str = Field(description="Yes/no visual question used for AI Vision tagging")
    phase_order: int = 0

    @field_validator("key")
    @classmethod
    def _valid_key(cls, value: str) -> str:
        if not _KEY.match(value):
            raise ValueError("activity key must be snake_case, 2-48 chars, starting with a letter")
        return value


class TaxonomySpec(BaseModel):
    activities: list[Activity] = Field(min_length=1, max_length=40)

    @field_validator("activities")
    @classmethod
    def _unique(cls, activities: list[Activity]) -> list[Activity]:
        keys = [a.key for a in activities]
        if len(keys) != len(set(keys)):
            raise ValueError("activity keys must be unique")
        return activities

    def keys(self) -> list[str]:
        return [a.key for a in self.activities]


def _a(key: str, label: str, description: str, question: str, order: int) -> Activity:
    return Activity(
        key=key, label=label, description=description, question=question, phase_order=order
    )


PRESETS: dict[str, TaxonomySpec] = {
    "water_infrastructure": TaxonomySpec(
        activities=[
            _a(
                "baseline_condition",
                "Baseline condition",
                "Site before works: bare ground, old or no water source, existing conditions.",
                "Does the image show a site before any construction work has started?",
                0,
            ),
            _a(
                "excavation",
                "Excavation / trenching",
                "Digging trenches or pits, excavators, open earthworks.",
                "Does the image show digging, trenching or an open excavation?",
                1,
            ),
            _a(
                "pipe_installation",
                "Pipe installation",
                "Pipes being laid, joined or placed in a trench.",
                "Does the image show pipes being laid or placed in a trench?",
                2,
            ),
            _a(
                "tank_construction",
                "Tank / structure construction",
                "Water tank, reservoir or structure under construction (foundation, walls, scaffolding).",
                "Does the image show a water tank or similar structure under construction?",
                3,
            ),
            _a(
                "testing_commissioning",
                "Testing & commissioning",
                "Pressure testing, taps being opened, meters, officials inspecting.",
                "Does the image show water systems being tested or inspected?",
                4,
            ),
            _a(
                "completed_infrastructure",
                "Completed infrastructure",
                "Finished tank, standpipe, tap stand or covered pipeline.",
                "Does the image show finished water infrastructure such as a completed tank or tap stand?",
                5,
            ),
            _a(
                "community_use",
                "Community use",
                "People collecting or using water from the new infrastructure.",
                "Does the image show people collecting or using water?",
                6,
            ),
        ]
    ),
    "reforestation": TaxonomySpec(
        activities=[
            _a(
                "baseline_condition",
                "Baseline condition",
                "Degraded or bare land before planting.",
                "Does the image show bare or degraded land before planting?",
                0,
            ),
            _a(
                "site_preparation",
                "Site preparation",
                "Clearing, pit digging, fencing, soil preparation.",
                "Does the image show land being cleared or pits being dug for planting?",
                1,
            ),
            _a(
                "nursery",
                "Nursery",
                "Seedlings in bags or trays in a nursery.",
                "Does the image show seedlings growing in a nursery?",
                2,
            ),
            _a(
                "sapling_planting",
                "Sapling planting",
                "People planting saplings in the ground.",
                "Does the image show saplings being planted?",
                3,
            ),
            _a(
                "maintenance_watering",
                "Maintenance / watering",
                "Watering, weeding, protective guards around young trees.",
                "Does the image show young trees being watered or maintained?",
                4,
            ),
            _a(
                "established_growth",
                "Established growth",
                "Established young trees or canopy cover.",
                "Does the image show established young trees or growing canopy?",
                5,
            ),
        ]
    ),
    "solar_energy": TaxonomySpec(
        activities=[
            _a(
                "baseline_condition",
                "Baseline condition",
                "Site or building before installation.",
                "Does the image show a roof or site before solar installation?",
                0,
            ),
            _a(
                "mounting_structure",
                "Mounting structure",
                "Frames, rails or poles being installed.",
                "Does the image show solar mounting frames or poles being installed?",
                1,
            ),
            _a(
                "panel_installation",
                "Panel installation",
                "Solar panels being fixed in place.",
                "Does the image show solar panels being installed?",
                2,
            ),
            _a(
                "electrical_work",
                "Electrical work",
                "Inverters, batteries, wiring, meters.",
                "Does the image show inverters, batteries or electrical wiring work?",
                3,
            ),
            _a(
                "completed_installation",
                "Completed installation",
                "Finished solar array or street lights.",
                "Does the image show a completed solar installation?",
                4,
            ),
            _a(
                "community_use",
                "Community use",
                "Lights on, devices charging, people using power.",
                "Does the image show people using solar-powered electricity?",
                5,
            ),
        ]
    ),
    "community_infrastructure": TaxonomySpec(
        activities=[
            _a(
                "baseline_condition",
                "Baseline condition",
                "Existing condition before works.",
                "Does the image show a site before works began?",
                0,
            ),
            _a(
                "construction",
                "Construction",
                "Building, repair or renovation in progress.",
                "Does the image show construction or repair work in progress?",
                1,
            ),
            _a(
                "completed_structure",
                "Completed structure",
                "Finished building, road, facility.",
                "Does the image show a completed building, road or facility?",
                2,
            ),
            _a(
                "training_event",
                "Training / community event",
                "Meetings, trainings, handovers.",
                "Does the image show a training session or community meeting?",
                3,
            ),
            _a(
                "community_use",
                "Community use",
                "People using the facility.",
                "Does the image show people using the facility?",
                4,
            ),
        ]
    ),
}

DEFAULT_PRESET = "water_infrastructure"


def preset(name: str) -> TaxonomySpec:
    try:
        return PRESETS[name].model_copy(deep=True)
    except KeyError as exc:
        raise ValueError(f"unknown taxonomy preset '{name}'. Options: {sorted(PRESETS)}") from exc
