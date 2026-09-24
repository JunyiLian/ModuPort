from __future__ import annotations
import sys
from pathlib import Path

class _AdapterCompatibilityProxy:
    """Decorate the validated adapter without changing its archived source."""
    def __init__(self,base):self._base=base
    def __getattr__(self,name):return getattr(self._base,name)
    def build_config(self,data):
        from .connection_stiffness import resolve_horizontal_connection
        cfg=self._base.build_config(data)
        r=resolve_horizontal_connection(data["horizontal_link"])
        cls=type(cfg.horizontal_connection)
        cfg.horizontal_connection=cls(cfg.horizontal_connection.name,*r.values)
        return cfg

def validation_root()->Path:
    here=Path(__file__).resolve()
    candidates=[here.parents[2]/"a20_validation"/"run_20260805_pilot",Path(r"E:\text\SCI\SCI-layout arrangement\Sap2000-api\a20_validation\run_20260805_pilot")]
    for p in candidates:
        if (p/"scripts"/"a20_rv30_moduport_adapter.py").exists():return p
    raise RuntimeError("validated RV30 runtime not found")

def imports():
    root=validation_root();sys.path.insert(0,str(root/"scripts")) if str(root/"scripts") not in sys.path else None
    import a20_rv30_moduport_adapter as adapter
    import a20_rv30_geometry_kernel as geometry
    return root,_AdapterCompatibilityProxy(adapter),geometry
