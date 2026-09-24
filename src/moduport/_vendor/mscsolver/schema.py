from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any
from .constants import CELL_PITCH, GEOMETRY_VERSION, SCHEMA_VERSION, SECTION_VERSION

def _conn(value: Any) -> dict:
    if isinstance(value, (int, float)):
        return {"ku1":float(value),"ku2":float(value),"ku3":float(value),"kr1":0.,"kr2":0.,"kr3":0.}
    out = dict(value)
    for k in ("ku1","ku2","ku3","kr1","kr2","kr3"): out[k] = float(out.get(k, 0.0))
    return out

@dataclass
class CaseDefinition:
    case_id: str
    grid_rows: int
    grid_cols: int
    storeys: int
    storey_layouts: list[str]
    horizontal_connection: dict
    vertical_connection: dict
    reference_point: list[float] | None = None
    geometry_version: str = GEOMETRY_VERSION
    section_version: str = SECTION_VERSION
    schema_version: str = SCHEMA_VERSION
    def normalize(self) -> dict:
        """Validate aliases and return the canonical public/internal case mapping."""
        if self.reference_point is None:
            self.reference_point=[self.grid_cols*CELL_PITCH/2,self.grid_rows*CELL_PITCH/2]
        if len(self.storey_layouts) != self.storeys: raise ValueError("one layout is required per storey")
        d=asdict(self);d["horizontal_connection"]=_conn(d["horizontal_connection"]);d["vertical_connection"]=_conn(d["vertical_connection"])
        d["storey_count"]=d["storeys"]
        d["horizontal_link_stiffness"]=dict(d["horizontal_connection"])
        d["vertical_link_stiffness"]=dict(d["vertical_connection"])
        return d
    @classmethod
    def from_dict(cls, d: dict) -> "CaseDefinition":
        """Construct a case definition from public or solver-compatible keys."""
        return cls(d["case_id"],int(d["grid_rows"]),int(d["grid_cols"]),int(d.get("storeys",d.get("storey_count"))),list(d["storey_layouts"]),d.get("horizontal_connection",d.get("horizontal_link_stiffness",1e8)),d.get("vertical_connection",d.get("vertical_link_stiffness",1e8)),d.get("reference_point"),d.get("geometry_version",GEOMETRY_VERSION),d.get("section_version",SECTION_VERSION),d.get("schema_version",SCHEMA_VERSION))
