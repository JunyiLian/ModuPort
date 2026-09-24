from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .exceptions import ConfigError

REQUIRED=("storey_layouts","storey_count","module_geometry","material","sections","horizontal_link","vertical_link","boundary")

@dataclass(frozen=True)
class ModelConfig:
    source: Path
    data: dict[str,Any]
    config_version: str
    layout: tuple[str,...]
    storeys: int
    module_geometry: dict[str,Any]
    material: dict[str,Any]
    sections: dict[str,Any]
    horizontal_link: dict[str,Any]
    vertical_link: dict[str,Any]
    boundary: dict[str,Any]
    load_cases: dict[str,list[float]]
    mass_model: str
    reinforced_zone: dict[str,Any]
    solver_options: dict[str,Any]

    @classmethod
    def from_json(cls,path:str|Path)->"ModelConfig":
        p=Path(path)
        try:d=json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:raise ConfigError(f"cannot read config {p}: {e}") from e
        missing=[k for k in REQUIRED if k not in d]
        if missing:raise ConfigError("missing required fields: "+", ".join(missing))
        layouts=tuple(d["storey_layouts"]);storeys=int(d["storey_count"])
        if len(layouts)!=storeys:raise ConfigError("storey_layouts length must equal storey_count")
        if d.get("units",{"force":"N","length":"mm"}) not in ({"force":"N","length":"mm"},{"length":"mm","force":"N"}):raise ConfigError("only N-mm units are supported")
        mass=d.get("mass_model","lumped")
        if mass not in ("lumped","consistent"):raise ConfigError("mass_model must be lumped or consistent")
        loads=d.get("load_cases",d.get("loads",{}))
        defaults={"reinforced_zone":dict(d.get("reinforced_zone",{}),active=bool(d.get("reinforced_zone_active",False))),"solver_options":d.get("solver_options",{"symmetry_tolerance":1e-10,"residual_tolerance":1e-8})}
        return cls(p,d,str(d.get("config_version",d.get("schema_version","1.0"))),layouts,storeys,d["module_geometry"],d["material"],d["sections"],d["horizontal_link"],d["vertical_link"],d["boundary"],loads,mass,defaults["reinforced_zone"],defaults["solver_options"])
